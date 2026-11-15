import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .feeds import MAX_FEED_BYTES, ParsedFeed, parse_feed
from .settings import BoardConfig, Feed, Settings
from .sources import parse_source, source_headers

logger = logging.getLogger("uvicorn.error")


@dataclass
class Board:
    config: BoardConfig
    snapshot: ParsedFeed | None = None
    updated_at: datetime | None = None
    failed: bool = False
    task: asyncio.Task[None] | None = None
    last_attempt: float | None = None


class BoardService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.boards = {key: Board(feed) for key, feed in settings.feeds.items()}
        self._slots = asyncio.Semaphore(4)

    async def _fetch(self, platform: str, source: Feed) -> ParsedFeed:
        url = source.url or (self.settings.base_url + (source.route or ""))
        async with asyncio.timeout(self.settings.timeout):
            async with self.client.stream("GET", url, headers=source_headers(source)) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_FEED_BYTES:
                        raise ValueError("Feed exceeds the maximum size")
                    content.extend(chunk)
                if source.adapter == "rss":
                    return parse_feed(bytes(content), platform, source, str(response.url))
                return parse_source(bytes(content), platform, source)

    async def _refresh(self, key: str, board: Board):
        board.last_attempt = asyncio.get_running_loop().time()
        platform = key.split("/", 1)[0]
        for source in board.config.sources:
            try:
                async with self._slots:
                    snapshot = await self._fetch(platform, source)
            except (httpx.HTTPError, ET.ParseError, ValueError, TimeoutError) as error:
                logger.warning("Board %s source %s failed: %s (%s)", key,
                               source.route or source.adapter, type(error).__name__, error)
                continue
            board.snapshot = snapshot
            board.updated_at = datetime.now(timezone.utc)
            board.failed = False
            return
        board.failed = True

    async def refresh(self, key: str):
        board = self.boards[key]
        if board.task is None or board.task.done():
            board.task = asyncio.create_task(self._refresh(key, board))
        # An individual client request can finish without cancelling a shared refresh.
        await asyncio.shield(board.task)

    async def run(self):
        while True:
            now = asyncio.get_running_loop().time()
            due = [key for key, board in self.boards.items()
                   if board.last_attempt is not None and
                   now - board.last_attempt >= (board.config.refresh_seconds or self.settings.refresh_interval)]
            await asyncio.gather(*(self.refresh(key) for key in due))
            await asyncio.sleep(self.settings.refresh_interval)

    async def close(self):
        tasks = [board.task for board in self.boards.values() if board.task and not board.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
