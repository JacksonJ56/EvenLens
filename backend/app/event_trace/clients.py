import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ValidationError

from .schemas import Evaluation, Extraction, SearchPlan
from .settings import TraceSettings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEEPSEEK_TOOLS = "https://api.deepseek.com/v1/tools"
LLM_STAGES = {SearchPlan: "制定搜索计划", Evaluation: "评估资料", Extraction: "提取时间线"}
T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    def __init__(self, service: str, message: str, status: int | None = None, timed_out: bool = False):
        self.service = service
        self.status = status
        self.timed_out = timed_out
        super().__init__(f"{service}：{message}")


class UnsafeURL(ValueError):
    pass


def public_url(value: str) -> str:
    """Reject untrusted URL forms before they can reach DNS or the Fetch service."""
    try:
        if len(value) > 8192 or re.search(r"[\x00-\x20\x7f\\]", value):
            raise ValueError
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.port not in {None, 443 if parsed.scheme == "https" else 80}):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                    or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid", ".onion"))
                    or not re.search(r"[a-z]", host.rsplit(".", 1)[1])
                    or re.fullmatch(r"(?:0x[\da-f]+|\d+)(?:\.(?:0x[\da-f]+|\d+))*", host)):
                raise ValueError
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError
        netloc = f"[{host}]" if ":" in host else host
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        raise UnsafeURL("网址不是允许的公网 HTTP(S) 地址") from None


def url_key(value: str) -> str:
    parsed = urlsplit(value)
    # Strip known tracking parameters for deduplication only. Preserve the source link.
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs = sorted((k, v) for k, v in pairs if not k.lower().startswith("utm_")
                   and k.lower() not in {"fbclid", "gclid", "msclkid"})
    return urlunsplit(("", parsed.netloc, parsed.path, urlencode(pairs), ""))


async def resolve_public(url: str) -> None:
    host = urlsplit(url).hostname
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, None, type=socket.SOCK_STREAM,
        )
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    except (OSError, ValueError):
        raise UnsafeURL("无法验证网址的公网解析") from None
    if not addresses or any(not ip.is_global or ip.is_multicast for ip in addresses):
        raise UnsafeURL("网址解析到了非公网地址")


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    summary: str = ""
    site_name: str | None = None
    date: str | None = None
    authority: int = -1
    rerank_score: float = 0


class SearchResponse(BaseModel):
    results: list[SearchHit]


class FetchedPage(BaseModel):
    title: str
    content: str


class TraceClients:
    def __init__(
        self, client: httpx.AsyncClient, settings: TraceSettings,
        resolve: Callable[[str], Awaitable[None]] = resolve_public,
    ):
        self.client = client
        self.settings = settings
        self.resolve = resolve
        self.timeout = httpx.Timeout(settings.call_timeout, connect=min(5, settings.call_timeout))

    async def _post(self, url: str, key: str, payload: dict, service: str) -> dict:
        for attempt in range(2):
            try:
                async with asyncio.timeout(self.settings.call_timeout):
                    async with self.client.stream(
                        "POST", url, json=payload, headers={"Authorization": f"Bearer {key}"},
                        follow_redirects=False, timeout=self.timeout,
                    ) as response:
                        status = response.status_code
                        if status != 200:
                            messages = {
                                401: "认证失败，请检查后端凭据", 402: "账户余额不足",
                                403: "上游拒绝了请求（权限或网址策略）", 404: "上游未返回可用内容",
                                429: "上游限流，请稍后重试", 504: "上游请求超时",
                            }
                            raise ProviderError(service, messages.get(status, "上游请求失败"), status, status in {408, 504})
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise ProviderError(service, "上游响应超过大小限制")
                            data.extend(chunk)
                        payload_json = json.loads(data)
                        if not isinstance(payload_json, dict):
                            raise ValueError("expected an object")
                        return payload_json
            except ProviderError as error:
                if attempt or error.status not in {408, 429, 500, 502, 503, 504}:
                    raise
            except (httpx.TimeoutException, TimeoutError):
                if attempt:
                    raise ProviderError(service, "请求超时", timed_out=True) from None
            except httpx.TransportError:
                if attempt:
                    raise ProviderError(service, "网络连接失败") from None
            except (ValueError, UnicodeError):
                raise ProviderError(service, "上游返回格式无效") from None
            await asyncio.sleep(0.35)
        raise AssertionError("unreachable")

    async def search(self, query: str) -> list[SearchHit]:
        name = "DeepSeek Search"
        result = await self._post(f"{DEEPSEEK_TOOLS}/search", self.settings.search_key, {
            "query": query, "count": self.settings.results_per_query, "need_content": False,
        }, name)
        try:
            return SearchResponse.model_validate(result).results[:self.settings.results_per_query]
        except ValidationError:
            raise ProviderError(name, "搜索响应不符合接口格式") from None

    async def fetch(self, url: str) -> FetchedPage:
        name = "DeepSeek Fetch"
        url = public_url(url)
        try:
            async with asyncio.timeout(min(4, self.settings.call_timeout)):
                await self.resolve(url)
        except TimeoutError:
            raise ProviderError(name, "网址解析超时", timed_out=True) from None
        result = await self._post(f"{DEEPSEEK_TOOLS}/fetch", self.settings.search_key, {"url": url}, name)
        try:
            page = FetchedPage.model_validate(result)
        except ValidationError:
            raise ProviderError(name, "正文响应不符合接口格式") from None
        if not page.content.strip():
            raise ProviderError(name, "未取得可用正文")
        return page

    async def structured(self, system: str, data: dict, schema: type[T]) -> T:
        stage = LLM_STAGES.get(schema)
        name = f"事件溯源 LLM（{stage}）" if stage else "事件溯源 LLM"
        payload = {
            "model": self.settings.llm_model, "response_format": {"type": "json_object"},
            "max_tokens": 4400,
            "messages": [
                {"role": "system", "content": system + "\nJSON Schema:\n" +
                 json.dumps(schema.model_json_schema(), ensure_ascii=False)},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
        }
        endpoint = urlsplit(self.settings.llm_base_url)
        if endpoint.scheme == "https" and endpoint.netloc == "api.deepseek.com" and self.settings.llm_model == "deepseek-flash":
            payload["thinking"] = {"type": "disabled"}
        output = await self._post(
            f"{self.settings.llm_base_url}/chat/completions", self.settings.llm_key, payload, name,
        )
        try:
            choice = output["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("incomplete response")
            return schema.model_validate_json(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise ProviderError(name, f"{schema.__name__} 输出无效") from None
