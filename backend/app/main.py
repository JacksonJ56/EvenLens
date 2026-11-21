import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from .boards import BoardService
from .event_trace.api import router as trace_router
from .event_trace.clients import TraceClients
from .event_trace.graph import create_graph
from .event_trace.settings import TraceSettings
from .settings import load_settings
from .public_opinion.api import router as opinion_router
from .public_opinion.settings import OpinionSettings
from .public_opinion.store import OpinionStore
from .public_opinion.workflow import OpinionTasks
from .public_opinion.network import PublicDNSResolver
from .public_opinion.sessions import PlatformSessions
from .public_opinion.session_api import router as session_router
from .copilot.api import router as copilot_router, CopilotJobs
from .copilot.store import CopilotStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    trace_settings = TraceSettings.from_env()
    async with httpx.AsyncClient(
        timeout=settings.timeout,
        follow_redirects=True,
        max_redirects=4,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    ) as client, httpx.AsyncClient(follow_redirects=False) as trace_client:
        service = BoardService(settings, client)
        app.state.board_service = service
        app.state.trace_settings = trace_settings
        app.state.trace_graph = create_graph(TraceClients(trace_client, trace_settings), trace_settings)
        app.state.trace_slots = asyncio.Semaphore(2)
        app.state.opinion_settings = OpinionSettings.from_env()
        app.state.opinion_sessions = PlatformSessions(app.state.opinion_settings)
        app.state.opinion_store = OpinionStore(app.state.opinion_settings.database_url)
        opinion_resolver = PublicDNSResolver(trace_client, enabled=app.state.opinion_settings.public_dns_fallback)
        app.state.copilot_clients = TraceClients(trace_client, trace_settings, resolve=opinion_resolver)
        app.state.copilot_store = CopilotStore(app.state.opinion_store.engine)
        app.state.copilot_jobs = CopilotJobs(app.state)
        app.state.opinion_tasks = OpinionTasks(app.state.opinion_store, TraceClients(trace_client, trace_settings, resolve=opinion_resolver),
                                             trace_settings, app.state.opinion_settings)
        worker = asyncio.create_task(service.run())
        try:
            yield
        finally:
            await app.state.copilot_jobs.close()
            await app.state.opinion_sessions.close()
            await app.state.opinion_tasks.close()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await service.close()


app = FastAPI(title="EventLens", lifespan=lifespan)
app.include_router(trace_router)
app.include_router(opinion_router)
app.include_router(session_router)
app.include_router(copilot_router)


@app.get("/api/boards/{platform}/{board}")
async def get_board(platform: str, board: str, request: Request, response: Response, refresh: bool = False):
    service: BoardService = request.app.state.board_service
    key = f"{platform}/{board}"
    entry = service.boards.get(key)
    headers = {"Cache-Control": "no-store"}
    if entry is None:
        raise HTTPException(404, "该榜单尚未接入", headers=headers)

    if refresh or (entry.snapshot is None and not entry.failed):
        await service.refresh(key)

    if entry.snapshot is None:
        raise HTTPException(503, "暂时无法从数据源获取榜单，请重试", headers=headers)

    response.headers.update(headers)
    return {
        "items": entry.snapshot.items,
        "mode": "live",
        "status": "stale" if entry.failed else "fresh",
        "updatedAt": entry.updated_at,
        "sourceTitle": entry.snapshot.title,
    }
