import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from .feeds import Entry, ParsedFeed, normalize, summary
from .settings import Feed

REPOSITORY = re.compile(r"/[\w.-]+/[\w.-]+", re.ASCII)
BVID = re.compile(r"BV[A-Za-z0-9]{10}")
SOURCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html, application/json",
}
REFERERS = {"weibo": "https://weibo.com/", "douyin": "https://www.douyin.com/", "bilibili": "https://www.bilibili.com/"}
REBANG_HOSTS = {
    "weibo": "weibo.com", "zhihu": "zhihu.com", "xiaohongshu": "xiaohongshu.com", "douyin": "douyin.com",
    "xueqiu": "xueqiu.com", "tieba": "tieba.baidu.com", "ithome": "ithome.com", "sspai": "sspai.com",
    "jiqizhixin": "jiqizhixin.com", "huxiu": "huxiu.com", "agirls": "agirls.aotter.net", "36kr": "36kr.com",
    "douban-media": "douban.com", "hongguo": "hongguoduanju.com", "gamersky": "gamersky.com",
    "douban-community": "douban.com", "hupu": "hupu.com", "tonghuashun": "10jqka.com.cn", "eastmoney": "eastmoney.com",
    "wallstreetcn": "wallstreetcn.com", "huggingface": "huggingface.co", "52pojie": "52pojie.cn", "infoq": "infoq.cn",
}


def source_headers(feed: Feed) -> dict[str, str] | None:
    if feed.adapter == "rss":
        return None
    referer = REFERERS.get(feed.adapter)
    return {**SOURCE_HEADERS, "Referer": referer} if referer else SOURCE_HEADERS


def field(row: dict, key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else str(value) if type(value) is int else ""


def source_rows(payload: object, *keys: str) -> list[dict]:
    for key in keys:
        payload = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("Board response did not contain the expected list")
    return payload


def original_url(value: str, domain: str) -> str:
    parts = urlsplit(value)
    host = parts.hostname or ""
    if (parts.scheme == "https" and (host == domain or host.endswith("." + domain))
            and parts.username is None and parts.password is None and parts.port in {None, 443}):
        return value
    return ""


def zhihu_entries(raw: bytes) -> list[Entry]:
    entries = []
    for row in source_rows(json.loads(raw), "data"):
        target = row.get("target")
        if not isinstance(target, dict):
            entries.append(Entry("", ""))
            continue
        question = field(target, "id")
        url = f"https://www.zhihu.com/question/{question}" if re.fullmatch(r"[0-9]+", question) else ""
        detail = field(row, "detail_text")
        heat = detail.removesuffix("热度").strip() if detail.endswith("热度") else ""
        entries.append(Entry(field(target, "title"), url, summary(field(target, "excerpt")), heat))
    return entries


def baidu_entries(raw: bytes) -> list[Entry]:
    match = re.search(r"<!--\s*s-data:(.*?)-->", raw.decode("utf-8"), re.DOTALL)
    if not match:
        raise ValueError("Baidu board data is missing")
    payload = json.loads(match.group(1))
    cards = source_rows(payload, "data", "cards")
    board = next((card for card in cards if card.get("component") == "hotList" and card.get("text") == "热搜榜"), None)
    rows = source_rows(board, "content")
    return [
        Entry(field(row, "word"), original_url(field(row, "url"), "baidu.com"),
              summary(field(row, "desc")), field(row, "hotScore"))
        for row in rows if not row.get("isTop")
    ]


def cctv_entries(raw: bytes) -> list[Entry]:
    match = re.fullmatch(r"\s*news\((.*)\)\s*;?\s*", raw.decode("utf-8-sig"), re.DOTALL)
    if not match:
        raise ValueError("CCTV news response is not the expected JSONP")
    return [
        Entry(field(row, "title"), original_url(field(row, "url"), "cctv.com"), summary(field(row, "brief")))
        for row in source_rows(json.loads(match.group(1)), "data", "list")
    ]


def wallstreetcn_day_entries(raw: bytes) -> list[Entry]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or field(payload, "code") != "20000":
        raise ValueError("WallstreetCN did not return a successful ranking")
    return [
        Entry(field(row, "title"), original_url(field(row, "uri"), "wallstreetcn.com"), metric=field(row, "pageviews"))
        for row in source_rows(payload, "data", "day_items")
    ]


PUBLIC_BOARD_PARSERS = {
    "zhihu": zhihu_entries, "baidu": baidu_entries, "cctv": cctv_entries, "wallstreetcn-day": wallstreetcn_day_entries,
}


def platform_entries(raw: bytes, adapter: str) -> list[Entry]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Expected a platform response object")
    status_key, success, list_key = {
        "weibo": ("ok", 1, "realtime"),
        "douyin": ("status_code", 0, "word_list"),
        "bilibili": ("code", 0, "list"),
    }[adapter]
    data = payload.get("data")
    rows = data.get(list_key) if isinstance(data, dict) else None
    if payload.get(status_key) != success or not isinstance(rows, list):
        raise ValueError("Platform did not return a valid ranking")
    entries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if adapter == "weibo":
            title = field(row, "word")
            query = urlencode({"q": field(row, "word_scheme") or title})
            entries.append(Entry(title, f"https://s.weibo.com/weibo?{query}", metric=field(row, "num")))
        elif adapter == "douyin":
            ident = field(row, "sentence_id")
            url = f"https://www.douyin.com/hot/{ident}" if ident.isascii() and ident.isdecimal() else ""
            entries.append(Entry(field(row, "word"), url, metric=field(row, "hot_value")))
        else:
            ident = field(row, "bvid")
            url = f"https://www.bilibili.com/video/{ident}" if BVID.fullmatch(ident) else ""
            entries.append(Entry(field(row, "title"), url, summary(field(row, "desc"))))
    if rows and not entries:
        raise ValueError("Platform ranking has no recognizable entries")
    return entries


class GitHubTrending(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_row = False
        self.in_heading = False
        self.entries = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.in_row = "Box-row" in (attrs.get("class") or "").split()
        elif self.in_row and tag == "h2":
            self.in_heading = True
        elif self.in_row and self.in_heading and tag == "a":
            href = attrs.get("href") or ""
            if REPOSITORY.fullmatch(href) and all(part not in {".", ".."} for part in href.split("/")[1:]):
                self.entries.append(Entry(href[1:], f"https://github.com{href}"))

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_row = False
        if tag in {"h2", "article"}:
            self.in_heading = False


class RebangRanking(HTMLParser):
    def __init__(self, source_url: str, platform: str):
        super().__init__()
        self.selected = False
        self.expected_tab = self.tabs(source_url)
        self.domain = REBANG_HOSTS.get(platform)
        self.entries = []

    @staticmethod
    def tabs(url: str) -> tuple[str, str]:
        query = parse_qs(urlsplit(url).query)
        return query.get("tab", [""])[0], query.get("sub_tab", [""])[0]

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href") or ""
        parts = urlsplit(href)
        if attrs.get("aria-current") == "page" and self.tabs(href) == self.expected_tab:
            self.selected = True
        if (attrs.get("data-item-title-link") == "true" and parts.scheme == "https" and self.domain
                and (parts.hostname == self.domain or (parts.hostname or "").endswith("." + self.domain))
                and not parts.username and not parts.password):
            title = (attrs.get("aria-label") or "").strip()
            self.entries.append(Entry(title, href))


class AllnetBilibiliRanking(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.heading = []
        self.entries = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_heading = True
        if tag != "a":
            return
        attrs = dict(attrs)
        if "data-list-item" not in (attrs.get("class") or "").split():
            return
        url = original_url(attrs.get("href") or "", "bilibili.com")
        if url and re.fullmatch(r"/video/BV[A-Za-z0-9]{10}/?", urlsplit(url).path):
            self.entries.append(Entry((attrs.get("data-title") or "").strip(), url))

    def handle_data(self, data):
        if self.in_heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_heading = False


class ArticleLinks(HTMLParser):
    def __init__(self, feed: Feed):
        super().__init__()
        self.base = feed.url or ""
        self.host = feed.link_host or urlsplit(self.base).hostname
        self.path = re.compile(feed.link_path or "")
        self.link_class = feed.link_class
        self.heading = feed.link_heading
        self.skip_heading_class = feed.skip_heading_class
        self.in_heading = False
        self.url = ""
        self.text = []
        self.entries = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == self.heading:
            self.in_heading = self.skip_heading_class not in (attrs.get("class") or "").split()
        if tag != "a":
            return
        self.url, self.text = "", []
        href = urljoin(self.base, attrs.get("href") or "")
        link = urlsplit(href)
        if (link.scheme == "https" and link.hostname == self.host and self.path.fullmatch(link.path)
                and (self.heading is None or self.in_heading)
                and (self.link_class is None or self.link_class in (attrs.get("class") or "").split())):
            self.url = href

    def handle_data(self, data):
        if self.url:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading:
            self.in_heading = False
        if tag == "a" and self.url:
            title = " ".join("".join(self.text).split())
            if title:
                self.entries.append(Entry(title, self.url))
            self.url = ""


def model_entries(raw: bytes) -> list[Entry]:
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("Expected Hugging Face model list")
    entries = []
    for row in rows:
        ident = field(row, "id") if isinstance(row, dict) else ""
        if REPOSITORY.fullmatch("/" + ident) and all(part not in {".", ".."} for part in ident.split("/")):
            entries.append(Entry(ident, f"https://huggingface.co/{ident}", metric=field(row, "likes")))
    if rows and not entries:
        raise ValueError("Model list has no recognizable entries")
    return entries


def parse_source(raw: bytes, platform: str, feed: Feed) -> ParsedFeed:
    if feed.adapter == "github":
        parser = GitHubTrending()
    elif feed.adapter == "rebang":
        parser = RebangRanking(feed.url or "", platform)
    elif feed.adapter == "links":
        parser = ArticleLinks(feed)
    elif feed.adapter == "allnet-bilibili":
        parser = AllnetBilibiliRanking()
    else:
        if parse := PUBLIC_BOARD_PARSERS.get(feed.adapter):
            entries = parse(raw)
        else:
            entries = model_entries(raw) if feed.adapter == "hf-models" else platform_entries(raw, feed.adapter)
        return normalize(entries, platform, feed.title or "", feed.metric_label)

    parser.feed(raw.decode("utf-8"))
    parser.close()
    wrong_tab = isinstance(parser, RebangRanking) and not parser.selected
    wrong_heading = isinstance(parser, AllnetBilibiliRanking) and "".join(parser.heading).strip() != feed.page_heading
    if not parser.entries or wrong_tab or wrong_heading:
        raise ValueError("Board page did not contain the expected ranking")
    return normalize(parser.entries, platform, feed.title or "", feed.metric_label)
