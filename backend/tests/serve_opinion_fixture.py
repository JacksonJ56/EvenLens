"""Explicit browser-test server, never imported by app.main.

Run from backend: .venv/bin/python -m uvicorn tests.serve_opinion_fixture:app --port 8002
Synthetic comments and a scripted model are visibly labelled TEST in every topic.
"""
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI

from app.public_opinion import workflow
from app.public_opinion.api import router
from app.public_opinion.schemas import Post
from app.public_opinion.store import OpinionStore
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.workflow import OpinionTasks
from app.event_trace.settings import TraceSettings
from tests.test_public_opinion import Provider, ScriptedModel
from tests.visualization_fixture import save_visualization_fixture


@asynccontextmanager
async def lifespan(app):
    with tempfile.TemporaryDirectory(prefix="eventlens-browser-test-") as directory:
        settings = OpinionSettings(f"sqlite:///{directory}/test.sqlite")
        app.state.opinion_settings = settings
        app.state.opinion_store = OpinionStore(settings.database_url)
        app.state.trace_settings = TraceSettings(llm_key="test-fixture-not-a-key", llm_model="scripted-test")
        workflow.make_model = lambda *args: ScriptedModel()
        app.state.board_service = SimpleNamespace(boards={f"{platform}/{board}": SimpleNamespace(
            snapshot=SimpleNamespace(items=items), updated_at=None) for platform, board in
            [("weibo", "hot"), ("xiaohongshu", "reads-3d"), ("xiaohongshu", "likes-3d"), ("ithome", "latest")]})
        app.state.opinion_tasks = OpinionTasks(app.state.opinion_store, Provider(), app.state.trace_settings, settings)
        app.state.visualization_task_id = save_visualization_fixture(app.state.opinion_store, settings)
        yield
        await app.state.opinion_tasks.close()


items = [{"id": "topic_01", "title": "【TEST 自动化验收】评论分析测试事件，并非真实热搜", "rank": 1,
          "url": "https://m.weibo.cn/detail/4982041758140155", "platform": "weibo"}]
app = FastAPI(title="TEST ONLY · Public Opinion UI fixture", lifespan=lifespan)
app.include_router(router)


@app.get("/test-case")
async def visualization_case():
    return {"task_id": app.state.visualization_task_id, "label": "TEST ONLY synthetic visualization report"}


@app.get("/api/boards/{platform}/{board}")
async def board(platform: str, board: str):
    return {"items": [{**item, "platform": platform} for item in items], "mode": "live", "status": "fresh",
            "updatedAt": None, "sourceTitle": "TEST ONLY 自动化验收数据，不是实际榜单"}
