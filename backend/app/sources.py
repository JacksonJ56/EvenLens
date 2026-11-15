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
    else:
        entries = model_entries(raw) if feed.adapter == "hf-models" else platform_entries(raw, feed.adapter)
        return normalize(entries, platform, feed.title or "", feed.metric_label)

    parser.feed(raw.decode("utf-8"))
    parser.close()
    if not parser.entries or isinstance(parser, RebangRanking) and not parser.selected:
        raise ValueError("Board page did not contain the expected ranking")
    return normalize(parser.entries, platform, feed.title or "", feed.metric_label)
