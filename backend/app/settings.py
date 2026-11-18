import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Feed:
    route: str | None = None
    metric_field: str | None = None
    metric_label: str | None = None
    url: str | None = None
    adapter: str = "rss"
    title: str | None = None
    link_path: str | None = None
    link_class: str | None = None
    link_heading: str | None = None
    link_host: str | None = None
    skip_heading_class: str | None = None
    page_heading: str | None = None


@dataclass(frozen=True)
class BoardConfig:
    sources: tuple[Feed, ...]
    refresh_seconds: float | None = None


@dataclass(frozen=True)
class Settings:
    base_url: str
    refresh_interval: float
    timeout: float
    feeds: dict[str, BoardConfig]


def positive_number(name: str, default: str) -> float:
    value = float(os.getenv(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    base_url = os.getenv("RSSHUB_BASE_URL", "http://127.0.0.1:1200").rstrip("/")
    base = urlsplit(base_url)
    if base.scheme not in {"http", "https"} or not base.netloc or base.query or base.fragment:
        raise ValueError("RSSHUB_BASE_URL must be an HTTP(S) base URL")

    config = Path(os.getenv("BOARD_ROUTES_FILE", "boards.json"))
    feeds = {}
    for key, value in json.loads((ROOT / config).read_text()).items():
        if "sources" in value:
            sources = tuple(Feed(**source) for source in value["sources"])
            board = BoardConfig(sources, value.get("refresh_seconds"))
        else:
            board = BoardConfig((Feed(**value),))
        if not board.sources or (board.refresh_seconds is not None and
                                 (not math.isfinite(board.refresh_seconds) or board.refresh_seconds <= 0)):
            raise ValueError(f"{key}: invalid sources or refresh interval")
        for feed in board.sources:
            if bool(feed.route) == bool(feed.url):
                raise ValueError(f"{key}: specify exactly one of route and url")
            if feed.adapter not in {
                "rss", "weibo", "bilibili", "douyin", "github", "rebang", "links", "hf-models",
                "zhihu", "baidu", "cctv", "wallstreetcn-day", "allnet-bilibili",
            }:
                raise ValueError(f"{key}: unsupported source adapter")
            if feed.adapter == "allnet-bilibili" and not feed.page_heading:
                raise ValueError(f"{key}: expected Bilibili board heading is required")
            if feed.adapter == "links":
                if not feed.link_path:
                    raise ValueError(f"{key}: link path required for HTML sources")
                re.compile(feed.link_path)
            if feed.route and (not feed.route.startswith("/") or feed.route.startswith("//") or feed.adapter != "rss"):
                raise ValueError(f"{key}: route must be an RSSHub path")
            if feed.url:
                url = urlsplit(feed.url)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                    raise ValueError(f"{key}: url must be a public HTTPS source")
                if feed.adapter != "rss" and not feed.title:
                    raise ValueError(f"{key}: direct sources need a title")
            if feed.adapter == "rss" and bool(feed.metric_field) != bool(feed.metric_label):
                raise ValueError(f"{key}: metric_field and metric_label must be paired")
        feeds[key] = board

    return Settings(
        base_url, positive_number("BOARD_REFRESH_SECONDS", "300"),
        positive_number("BOARD_REQUEST_TIMEOUT_SECONDS", "15"), feeds,
    )
