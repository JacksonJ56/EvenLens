import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def bounded_int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class TraceSettings:
    search_key: str = field(default="", repr=False)
    llm_key: str = field(default="", repr=False)
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = ""
    results_per_query: int = 10
    max_rounds: int = 3
    max_queries: int = 3
    max_fetch: int = 9
    parallel: int = 3
    call_timeout: int = 18
    task_timeout: int = 100

    @classmethod
    def from_env(cls) -> "TraceSettings":
        base = os.getenv("EVENT_TRACE_LLM_BASE_URL", cls.llm_base_url).rstrip("/")
        parsed = urlsplit(base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.query or parsed.fragment):
            raise ValueError("EVENT_TRACE_LLM_BASE_URL must be an HTTP(S) base URL")
        return cls(
            search_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            llm_key=os.getenv("EVENT_TRACE_LLM_API_KEY", "").strip(),
            llm_base_url=base,
            llm_model=os.getenv("EVENT_TRACE_LLM_MODEL", "").strip(),
            results_per_query=bounded_int("DEEPSEEK_SEARCH_MAX_RESULTS", 10, 1, 20),
            max_rounds=bounded_int("EVENT_TRACE_MAX_ROUNDS", 3, 1, 5),
            max_queries=bounded_int("EVENT_TRACE_MAX_QUERIES", 3, 1, 5),
            max_fetch=bounded_int("EVENT_TRACE_MAX_FETCH", 9, 1, 20),
            parallel=bounded_int("EVENT_TRACE_PARALLEL", 3, 1, 5),
            call_timeout=bounded_int("EVENT_TRACE_CALL_TIMEOUT_SECONDS", 18, 3, 45),
            task_timeout=bounded_int("EVENT_TRACE_TIMEOUT_SECONDS", 100, 10, 120),
        )
