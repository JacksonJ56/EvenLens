import asyncio
import hashlib
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response

from ..boards import BoardService
from .clients import ProviderError
from .schemas import EventTraceRequest, EventTraceResponse, SelectedHotEvent
from .settings import TraceSettings

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-store"}
logger = logging.getLogger("uvicorn.error")


def trace_cache_key(payload) -> str:
    """Share recent completed traces with Copilot without changing trace execution."""
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    identity = ["event_trace", data["selection"]["platform_id"], data["selection"]["feed_id"],
                {k: data["event"].get(k) for k in ["id", "title", "url"]}, int(time.time() // 21600)]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def canonical_event(payload: EventTraceRequest, service: BoardService) -> EventTraceRequest:
    selection = payload.selection
    if selection.board_id is not None and selection.board_id != selection.feed_id:
        raise HTTPException(422, "所选榜单与数据源不一致", headers=NO_CACHE)
    board = service.boards.get(f"{selection.platform_id}/{selection.feed_id}")
    if not board or not board.snapshot:
        raise HTTPException(409, "服务端暂无所选榜单快照，请刷新热点后再试", headers=NO_CACHE)
    item = next((item for item in board.snapshot.items if item["id"] == payload.event.id), None)
    if item is None:
        raise HTTPException(409, "所选热点已不在最新榜单，请刷新并重新选择", headers=NO_CACHE)
    summary = item.get("preview", {}).get("summary")
    return payload.model_copy(update={"event": SelectedHotEvent(
        id=item["id"], title=item["title"][:1000], url=item["url"][:8192] or None,
        summary=summary[:2000] if summary else None, rank=item.get("rank"), captured_at=board.updated_at,
    )})


async def wait_for_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


@router.post("/api/event-trace", response_model=EventTraceResponse)
async def event_trace(payload: EventTraceRequest, request: Request, response: Response) -> EventTraceResponse:
    state = request.app.state
    settings: TraceSettings = state.trace_settings
    if not settings.search_key:
        raise HTTPException(503, "事件溯源未配置 DeepSeek Search 凭据（DEEPSEEK_API_KEY）", headers=NO_CACHE)
    if not settings.llm_key or not settings.llm_model:
        raise HTTPException(503, "事件溯源未配置模型凭据或模型名（EVENT_TRACE_LLM_API_KEY / EVENT_TRACE_LLM_MODEL）", headers=NO_CACHE)
    selected = canonical_event(payload, state.board_service)
    if state.trace_slots.locked():
        raise HTTPException(429, "事件溯源任务正在处理，请稍后重试", headers=NO_CACHE)

    async with state.trace_slots:
        investigate = asyncio.create_task(state.trace_graph.ainvoke(
            {"selected_event": selected}, {"recursion_limit": settings.max_rounds * 3 + 10},
        ))
        disconnected = asyncio.create_task(wait_for_disconnect(request))
        try:
            async with asyncio.timeout(settings.task_timeout):
                done, _ = await asyncio.wait({investigate, disconnected}, return_when=asyncio.FIRST_COMPLETED)
                if investigate not in done:
                    raise HTTPException(499, "客户端已取消任务", headers=NO_CACHE)
                output = investigate.result()
        except TimeoutError:
            logger.warning("事件溯源超过 %s 秒的任务总时限", settings.task_timeout)
            raise HTTPException(504, "事件溯源超时，请稍后重试", headers=NO_CACHE) from None
        except ProviderError as error:
            logger.warning("%s（上游状态 %s）", error, error.status or "无")
            raise HTTPException(504 if error.timed_out else 502, str(error), headers=NO_CACHE) from None
        finally:
            investigate.cancel()
            disconnected.cancel()
            await asyncio.gather(investigate, disconnected, return_exceptions=True)
    response.headers.update(NO_CACHE)
    store = getattr(state, "opinion_store", None)
    if store is not None:
        store.cache_put(trace_cache_key(selected), output["response"].model_dump(mode="json"))
    return output["response"]
