import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .settings import Feed

MAX_FEED_BYTES = 2_000_000


class FeedTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("DTD is not allowed in feeds")


class SummaryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def text(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def summary(value: str) -> str:
    parser = SummaryParser()
    parser.feed(value)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)[:2000]


def entry_url(entry: ET.Element, base: str) -> str:
    for link in entry.findall("{*}link"):
        if link.get("rel", "alternate") != "alternate":
            continue
        value = (link.get("href") or text(link)).strip()
        if not value:
            continue
        try:
            url = urljoin(base, value)
            parts = urlsplit(url)
            if parts.scheme in {"http", "https"} and parts.hostname and not parts.username and not parts.password:
                return url
        except ValueError:
            continue
    return ""


@dataclass(frozen=True)
class ParsedFeed:
    title: str
    items: list[dict]


@dataclass(frozen=True)
class Entry:
    title: str
    url: str
    excerpt: str = ""
    metric: str = ""


def normalize(entries: list[Entry], platform: str, source_title: str, metric_label: str | None) -> ParsedFeed:
    items = []
    seen = set()
    for entry in entries:
        title, url = entry.title, entry.url
        if not title or not url or (title, url) in seen:
            continue
        seen.add((title, url))
        item = {
            "id": hashlib.sha256(f"{platform}\n{title}\n{url}".encode()).hexdigest()[:24],
            "title": title, "url": url, "rank": len(items) + 1, "platform": platform,
        }
        if entry.metric and metric_label:
            item["metric"] = {"value": entry.metric, "label": metric_label}
        if entry.excerpt and entry.excerpt != title:
            item["preview"] = {"summary": entry.excerpt}
        items.append(item)
        if len(items) >= 50:
            break

    if entries and not items:
        raise ValueError("Feed entries contain no valid title and link")
    return ParsedFeed(source_title, items)


def parse_feed(content: bytes, platform: str, feed: Feed, response_url: str) -> ParsedFeed:
    root = ET.fromstring(content, parser=ET.XMLParser(target=FeedTreeBuilder()))
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise ValueError("RSS channel is missing")
        entries = channel.findall("item")
    elif root.tag == "{http://www.w3.org/2005/Atom}feed":
        channel = root
        entries = root.findall("{*}entry")
    else:
        raise ValueError("Response is neither RSS nor Atom")

    source_title = feed.title or summary(text(channel.find("{*}title")))
    base = entry_url(channel, response_url) or response_url
    return normalize([
        Entry(
            summary(text(entry.find("{*}title"))),
            entry_url(entry, base),
            summary(text(entry.find("{*}description")) or text(entry.find("{*}summary"))),
            text(entry.find(feed.metric_field)) if feed.metric_field else "",
        ) for entry in entries
    ], platform, source_title, feed.metric_label)
