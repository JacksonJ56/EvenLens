import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from .boards import BoardService
from .settings import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    async with httpx.AsyncClient(
        timeout=settings.timeout,
        follow_redirects=True,
        max_redirects=4,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    ) as client:
        service = BoardService(settings, client)
        app.state.board_service = service
        worker = asyncio.create_task(service.run())
        try:
            yield
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await service.close()


app = FastAPI(title="EventLens Boards", lifespan=lifespan)


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
