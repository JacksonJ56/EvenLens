"""Bounded adapter for a separately installed, authorized MediaCrawler checkout.

No crawler source is vendored or changed. The worker attaches a minimal store sink to the
upstream store factory so callback order survives, and stops after N root comments.
"""
import asyncio
import json
import os
import re
import signal
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .schemas import CommentInput, Post
from .settings import OpinionSettings, PLATFORMS

POST_PATTERNS = {
    "xiaohongshu": (r"(?:www\.)?xiaohongshu\.com", r"/(?:explore|discovery/item)/([a-fA-F0-9]{24})(?:/|$)"),
    "kuaishou": (r"(?:www\.)?kuaishou\.com", r"/short-video/([a-zA-Z0-9_-]+)(?:/|$)"),
    "bilibili": (r"(?:www\.)?bilibili\.com", r"/video/(BV[a-zA-Z0-9]{10}|av\d+)(?:/|$)"),
    "weibo": (r"(?:www\.|m\.)?weibo\.(?:com|cn)", r"/(?:detail|status)/([0-9]+)(?:/|$)"),
    "tieba": (r"tieba\.baidu\.com", r"/p/(\d+)(?:/|$)"),
}


def worker_environment() -> dict[str, str]:
    # Never forward EventLens LLM/search/database credentials to the third-party process.
    names = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP", "DISPLAY",
             "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
             "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
             "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_NODEJS_PATH"}
    return {key: value for key, value in os.environ.items() if key in names}


def identify_post(platform: str, url: str) -> str | None:
    from ..event_trace.clients import public_url, UnsafeURL
    try:
        parsed = urlsplit(public_url(url))
    except UnsafeURL:
        return None
    host_pattern, path_pattern = POST_PATTERNS.get(platform, ("(?!)", "(?!)"))
    if not re.fullmatch(host_pattern, parsed.hostname or ""):
        return None
    match = re.match(path_pattern, parsed.path)
    if match:
        return match.group(1)
    # MediaCrawler's Weibo detail accepts decimal mids, not base62 status IDs.
    if platform == "weibo" and re.fullmatch(r"/\d+/\d+/?", parsed.path):
        return parsed.path.strip("/").split("/")[-1]
    return None


def normalized_time(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
        if number <= 0:
            return None
        return datetime.fromtimestamp(number / 1000 if number > 10**11 else number, timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if len(str(value)) <= 10:
                return None  # A publication date alone is not an exact post timestamp.
            if parsed.tzinfo is None:
                from zoneinfo import ZoneInfo
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return parsed
        except ValueError:
            return None


def map_comment(raw: dict, post: Post, rank: int, sort_mode="unknown") -> CommentInput | None:
    identifier = raw.get("comment_id")
    if identifier is None or str(identifier) in {"", "None", "0"}:
        return None
    parent = raw.get("parent_comment_id")
    parent = str(parent) if parent not in {None, "", "0", 0} else None
    likes = raw.get("like_count", raw.get("comment_like_count"))
    try:
        likes = max(0, int(likes)) if likes is not None else None
    except (ValueError, TypeError):
        likes = None
    return CommentInput(platform_id=post.platform_id, post_id=post.id, comment_id=str(identifier),
                        content=str(raw.get("content") or "")[:30000], source_rank=rank, sort_mode=sort_mode,
                        parent_comment_id=parent, created_at=normalized_time(raw.get("create_time", raw.get("publish_time"))),
                        like_count=likes, source_url=post.url, collected_at=datetime.now(timezone.utc))


class MediaCrawlerAdapter:
    def __init__(self, settings: OpinionSettings):
        self.settings = settings

    async def preflight(self):
        """Check dependencies, the verified detail argument, and Chromium before paid discovery.

        This does not log in, visit a platform, or claim a working session.
        """
        code = (
            "import inspect,pathlib,main,cmd_arg; from playwright.sync_api import sync_playwright; "
            "assert '--specified_id' in inspect.getsource(cmd_arg.parse_cmd); "
            "p=sync_playwright().start(); available=pathlib.Path(p.chromium.executable_path).is_file(); "
            "assert available; b=p.chromium.launch(headless=True); b.close(); p.stop()"
        )
        process = await asyncio.create_subprocess_exec(self.settings.crawler_python, "-c", code,
            cwd=self.settings.crawler_home, env=worker_environment(), stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        try:
            await asyncio.wait_for(process.wait(), 15)
        except TimeoutError:
            raise ValueError("MediaCrawler 运行环境检查超时，请核对独立虚拟环境") from None
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        if process.returncode:
            raise ValueError("MediaCrawler 依赖、detail 接口版本或 Chromium 启动检查失败；请检查独立环境和浏览器运行权限，也可导入授权评论。")

    async def collect(self, posts: list[Post]):
        rows, warnings = [], []
        for post in posts[:self.settings.max_posts]:
            ready, reason = self.settings.collector_status(post.platform_id)
            if not ready:
                raise ValueError(reason)
            code = PLATFORMS[post.platform_id]
            with tempfile.TemporaryDirectory(prefix="eventlens-comments-") as work:
                output = Path(work) / "comments.jsonl"
                env = {**worker_environment(), f"MEDIACRAWLER_COOKIES_{code.upper()}": os.environ[f"MEDIACRAWLER_COOKIES_{code.upper()}"],
                       "EVENTLENS_MC_CODE": code, "EVENTLENS_MC_URL": post.url,
                       "EVENTLENS_MC_ID": post.id, "EVENTLENS_MC_OUTPUT": str(output),
                       "EVENTLENS_MC_LIMIT": str(self.settings.per_post), "PYTHONUNBUFFERED": "1"}
                process = await asyncio.create_subprocess_exec(
                    self.settings.crawler_python, str(Path(__file__).with_name("crawler_worker.py")),
                    cwd=self.settings.crawler_home, env=env, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                )
                try:
                    async with asyncio.timeout(self.settings.collector_timeout):
                        await process.wait()
                except TimeoutError:
                    warnings.append(f"帖子 {post.id} 采集超时，仅保留已返回的评论。")
                finally:
                    if process.returncode is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            await asyncio.wait_for(process.wait(), 3)
                        except TimeoutError:
                            os.killpg(process.pid, signal.SIGKILL)
                            await process.wait()
                if process.returncode not in {0, None}:
                    warnings.append(f"帖子 {post.id} 采集未完整结束；请检查会话、Chromium 和上游版本。")
                if output.exists():
                    # Worker writes only minimized fields, in awaited callback order.
                    for line in output.read_text().splitlines()[:self.settings.per_post]:
                        try:
                            raw = json.loads(line)
                            row = map_comment(raw, post, raw.pop("_source_rank"), raw.pop("_sort_mode", "unknown"))
                            if row:
                                rows.append(row)
                        except (ValueError, TypeError, KeyError):
                            warnings.append(f"帖子 {post.id} 的一条损坏记录已过滤。")
                metadata=output.with_suffix('.status.json')
                if code=='tieba' and metadata.is_file() and metadata.stat().st_size<1000:
                    status=json.loads(metadata.read_text()).get('status')
                    if status=='restricted':
                        if not rows:raise ValueError('贴吧要求本人登录或安全验证，已停止采集；请在官方页面确认会话，不会绕过限制。')
                        warnings.append('贴吧要求本人验证，已停止后续采集，仅保留实际取得的评论。');break
                    if status!='completed':warnings.append(f'贴吧帖子 {post.id} 未完整读取，仅保留实际返回的评论（{status}）。')
        if any(post.platform_id=='tieba' for post in posts):
            warnings.append('贴吧按页面返回的楼层顺序读取一级回复，排除原帖与楼中楼；未确认热门排序，不代表热门评论或全平台观点。')
        if not rows:
            raise ValueError("采集未返回有效评论：检查合法会话、平台访问限制或 MediaCrawler 版本；也可导入授权评论。")
        return rows, warnings
