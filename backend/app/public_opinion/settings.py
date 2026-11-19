import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..event_trace.settings import bounded_int

# EventLens IDs, not translated display names. Kuaishou is intentionally not added to the catalog.
PLATFORMS = {"xiaohongshu": "xhs", "douyin": "dy", "kuaishou": "ks", "bilibili": "bili",
             "weibo": "wb", "tieba": "tieba", "zhihu": "zhihu"}


@dataclass(frozen=True)
class OpinionSettings:
    database_url: str
    crawler_home: str = ""
    crawler_python: str = "python"
    crawler_authorized: bool = False
    max_posts: int = 20
    per_post: int = 50
    max_comments: int = 1000
    max_replies: int = 100
    max_searches: int = 5
    max_fetches: int = 15
    context_searches: int = 3
    discovery_timeout: int = 90
    task_timeout: int = 600
    collector_timeout: int = 60
    max_model_calls: int = 60
    max_tokens: int = 120000
    batch_bytes: int = 10000
    model_output: int = 2500
    comment_chars: int = 1200
    tool_timeout: int = 180
    context_timeout: int = 60
    context_tokens: int = 40000
    public_dns_fallback: bool = False

    @classmethod
    def from_env(cls):
        root = Path(__file__).resolve().parents[2] / "data"
        root.mkdir(exist_ok=True)
        return cls(
            database_url=os.getenv("PUBLIC_OPINION_DATABASE_URL", f"sqlite:///{root / 'public_opinion.sqlite3'}"),
            crawler_home=os.getenv("MEDIACRAWLER_HOME", ""),
            crawler_python=os.getenv("MEDIACRAWLER_PYTHON", "python"),
            crawler_authorized=os.getenv("MEDIACRAWLER_AUTHORIZED", "false").lower() == "true",
            max_posts=bounded_int("PUBLIC_OPINION_MAX_POSTS", 20, 1, 20),
            per_post=bounded_int("PUBLIC_OPINION_COMMENTS_PER_POST", 50, 1, 100),
            max_comments=bounded_int("PUBLIC_OPINION_MAX_COMMENTS", 1000, 1, 1000),
            max_replies=bounded_int("PUBLIC_OPINION_MAX_REPLIES", 100, 0, 200),
            max_searches=bounded_int("PUBLIC_OPINION_DISCOVERY_SEARCHES", 5, 1, 8),
            max_fetches=bounded_int("PUBLIC_OPINION_DISCOVERY_FETCHES", 15, 1, 20),
            context_searches=bounded_int("PUBLIC_OPINION_CONTEXT_SEARCHES", 3, 0, 5),
            discovery_timeout=bounded_int("PUBLIC_OPINION_DISCOVERY_TIMEOUT", 90, 10, 180),
            task_timeout=bounded_int("PUBLIC_OPINION_TASK_TIMEOUT", 600, 30, 1200),
            collector_timeout=bounded_int("PUBLIC_OPINION_COLLECTOR_TIMEOUT", 60, 10, 120),
            max_model_calls=bounded_int("PUBLIC_OPINION_MODEL_CALLS", 60, 2, 100),
            max_tokens=bounded_int("PUBLIC_OPINION_TOKEN_BUDGET", 120000, 5000, 200000),
            batch_bytes=bounded_int("PUBLIC_OPINION_BATCH_BYTES", 10000, 4000, 18000),
            model_output=bounded_int("PUBLIC_OPINION_MODEL_OUTPUT_TOKENS", 2500, 1000, 4096),
            comment_chars=bounded_int("PUBLIC_OPINION_COMMENT_CHARS", 1200, 200, 2400),
            tool_timeout=bounded_int("PUBLIC_OPINION_TOOL_TIMEOUT", 180, 15, 300),
            context_timeout=bounded_int("PUBLIC_OPINION_CONTEXT_TIMEOUT", 60, 10, 120),
            context_tokens=bounded_int("PUBLIC_OPINION_CONTEXT_TOKEN_BUDGET", 40000, 5000, 100000),
            public_dns_fallback=os.getenv("PUBLIC_OPINION_PUBLIC_DNS_FALLBACK", "false").lower() == "true",
        )

    def collector_status(self, platform: str) -> tuple[bool, str]:
        code = PLATFORMS.get(platform)
        if not code:
            return False, "当前平台暂不支持公众舆情分析，请重新选择支持的平台。"
        if not self.crawler_authorized:
            return False, "未确认 MediaCrawler 非商业学习研究用途及平台数据访问授权；可导入合法评论文件。"
        if not (Path(self.crawler_home) / "main.py").is_file():
            return False, "未配置可用的 MEDIACRAWLER_HOME；可导入合法评论文件。"
        if not shutil.which(self.crawler_python):
            return False, "MEDIACRAWLER_PYTHON 不是可用的 Python 程序；可导入合法评论文件。"
        if not os.getenv(f"MEDIACRAWLER_COOKIES_{code.upper()}", "").strip():
            return False, "未配置该平台的合法 Cookie 会话；可导入合法评论文件。"
        return True, "采集适配器已配置；实际可访问性仍取决于平台会话与访问限制。"
