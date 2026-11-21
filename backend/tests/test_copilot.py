"""Authenticated bridge tests. No live models, search, login or collection."""

import asyncio
import hashlib
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from app.copilot.api import router, CopilotJobs
from app.copilot.store import CopilotStore
from app.public_opinion.store import OpinionStore
from app.public_opinion.schemas import OpinionRequest
from app.event_trace.settings import TraceSettings
from app.event_trace.clients import FetchedPage, SearchHit, UnsafeURL

PAGE = {
    "category_id": "general",
    "category_name": "综合",
    "platform_id": "weibo",
    "platform_name": "微博",
    "feed_id": "hot",
    "board_id": None,
    "board_name": "热搜",
}


class CopilotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpinionStore(
            "sqlite:///" + str(Path(self.temp.name) / "test.sqlite")
        )
        self.app = FastAPI()
        self.app.include_router(router)
        s = self.app.state
        s.trace_settings = TraceSettings(llm_key="TEST_SECRET", llm_model="TEST")
        s.opinion_store = self.store
        s.copilot_store = CopilotStore(self.store.engine)
        s.copilot_jobs = CopilotJobs(s)
        self.item = {
            "id": "event1",
            "title": "真实来源标题",
            "rank": 1,
            "url": "https://example.com/original",
            "preview": {"summary": "来源摘要"},
        }
        s.board_service = SimpleNamespace(
            boards={
                "weibo/hot": SimpleNamespace(
                    snapshot=SimpleNamespace(items=[self.item], title="来源"),
                    updated_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
                    failed=False,
                )
            },
            refresh=AsyncMock(),
        )
        s.copilot_clients = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    SearchHit(title="来源报道", url="https://example.com/news")
                ]
            ),
            fetch=AsyncMock(
                return_value=FetchedPage(title="来源报道", content="真实正文")
            ),
        )
        s.trace_graph = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value={
                    "response": SimpleNamespace(
                        model_dump=lambda **kw: {
                            "status": "partial",
                            "subject": "TEST topic",
                            "timeline": [],
                            "sources": [],
                        }
                    )
                }
            )
        )
        s.trace_slots = asyncio.Semaphore(2)
        token = hashlib.sha256(b"TEST_SECRET\nEventLens Copilot").hexdigest()
        self.headers = {"X-EventLens-Copilot": token, "X-Copilot-Owner": "a" * 64}
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://test",
            headers=self.headers,
        )
        self.thread = (await self.client.get("/api/copilot/threads")).json()[
            "thread_id"
        ]

    async def asyncTearDown(self):
        await self.app.state.copilot_jobs.close()
        await self.client.aclose()
        self.store.engine.dispose()
        self.temp.cleanup()

    async def begin(self, page=None, **extra):
        return await self.client.post(
            "/api/copilot/begin",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "page": page or PAGE,
                **extra,
            },
        )

    async def tool(self, name, args):
        return await self.client.post(
            "/api/copilot/tools",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "name": name,
                "args": args,
            },
        )

    async def test_service_and_thread_ownership(self):
        self.assertEqual(
            (
                await self.client.get(
                    "/api/copilot/threads", headers={"X-EventLens-Copilot": "bad"}
                )
            ).status_code,
            403,
        )
        other = {**self.headers, "X-Copilot-Owner": "c" * 64}
        self.assertEqual(
            (
                await self.client.get(
                    "/api/copilot/threads?id=" + self.thread, headers=other
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/copilot/begin",
                    headers=other,
                    json={
                        "thread_id": self.thread,
                        "request_id": "b" * 32,
                        "page": PAGE,
                    },
                )
            ).status_code,
            404,
        )
        self.assertNotIn(
            "TEST_SECRET",
            (await self.client.get("/api/copilot/threads?id=" + self.thread)).text,
        )

    async def test_current_rank_canonical_reference_and_mock_scope(self):
        r = await self.begin(
            reference={
                "category_id": "general",
                "platform_id": "weibo",
                "feed_id": "hot",
                "id": "event1",
            }
        )
        self.assertEqual(r.status_code, 200, r.text)
        ctx = r.json()["context"]
        self.assertEqual(ctx["items"][0]["rank"], 1)
        self.assertEqual(ctx["reference"]["title"], self.item["title"])
        self.assertEqual(ctx["reference"]["url"], self.item["url"])
        self.assertEqual((await self.begin()).status_code, 409)
        await self.client.post(
            "/api/copilot/finish",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "history": [],
                "messages": [],
            },
        )
        r = await self.begin(mode="mock")
        self.assertEqual(r.json()["context"]["items"], [])
        self.assertIn("演示", r.json()["context"]["warning"])

    async def test_invalid_context_and_unverified_event(self):
        r = await self.begin(
            reference={
                "category_id": "general",
                "platform_id": "weibo",
                "feed_id": "hot",
                "id": "forged",
            }
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual((await self.begin()).status_code, 200)  # error released lease
        self.assertEqual(
            (
                await self.tool(
                    "get_hotspot_detail", {"event_key": "https://evil.example/fake"}
                )
            ).status_code,
            422,
        )

    async def test_followup_survives_board_change_and_history_isolated(self):
        await self.begin()
        detail = await self.tool(
            "get_hotspot_detail", {"event_key": "weibo/hot/event1"}
        )
        self.assertEqual(detail.json()["data"]["event"]["title"], self.item["title"])
        await self.client.post(
            "/api/copilot/finish",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "history": [
                    {"role": "user", "content": "这个事件是什么", "timestamp": 1}
                ],
                "messages": [{"id": "u", "role": "user", "content": "这个事件是什么"}],
            },
        )
        self.app.state.board_service.boards["baidu/hot"] = SimpleNamespace(
            snapshot=SimpleNamespace(
                items=[{**self.item, "id": "event2", "title": "另一事件"}]
            ),
            updated_at="2026-11-21T00:01:00Z",
            failed=False,
        )
        r = await self.begin({**PAGE, "platform_id": "baidu", "platform_name": "百度"})
        self.assertEqual(r.json()["context"]["active_event"]["id"], "event1")
        self.assertEqual(r.json()["context"]["items"][0]["id"], "event2")
        other = (await self.client.get("/api/copilot/threads")).json()
        self.assertEqual(other["messages"], [])

    async def test_simple_details_do_not_start_expensive_work(self):
        await self.begin()
        r = await self.tool("get_hotspot_detail", {"event_key": "weibo/hot/event1"})
        self.assertEqual(r.status_code, 200)
        self.app.state.trace_graph.ainvoke.assert_not_awaited()
        self.app.state.copilot_clients.search.assert_not_awaited()

    async def test_old_turn_cannot_invoke_tools_on_new_lease(self):
        await self.begin()
        response = await self.client.post(
            "/api/copilot/tools",
            json={
                "thread_id": self.thread,
                "request_id": "c" * 32,
                "name": "web_search",
                "args": {"query": "TEST"},
            },
        )
        self.assertEqual(response.status_code, 409)
        self.app.state.copilot_clients.search.assert_not_awaited()

    async def test_lab_selected_event_is_verified_from_real_snapshot(self):
        response = await self.begin(selected_event_id="event1")
        self.assertEqual(
            response.json()["context"]["selected_event"]["title"], self.item["title"]
        )
        self.assertIsInstance(
            response.json()["context"]["selected_event"]["captured_at"], str
        )

    async def test_global_search_keeps_catalog_category_and_board(self):
        page = {
            **PAGE,
            "category_id": "tech",
            "category_name": "科技",
            "platform_id": "ithome",
            "platform_name": "IT之家",
            "feed_id": "latest",
            "board_id": "latest",
            "board_name": "IT资讯最新",
        }
        self.app.state.board_service.boards["ithome/latest"] = SimpleNamespace(
            snapshot=SimpleNamespace(items=[self.item]), updated_at=None, failed=False
        )
        response = await self.begin(catalog=[page])
        self.assertEqual(response.status_code, 200)
        response = await self.tool(
            "search_hotspots", {"query": "真实来源", "platform_id": "ithome"}
        )
        key = response.json()["data"]["items"][0]["event_key"]
        detail = (await self.tool("get_hotspot_detail", {"event_key": key})).json()[
            "data"
        ]
        self.assertEqual(detail["selection"]["category_id"], "tech")
        self.assertEqual(detail["selection"]["board_name"], "IT资讯最新")

    async def test_tools_reuse_search_fetch_and_ssrf_guard(self):
        await self.begin()
        r = await self.tool("web_search", {"query": "TEST"})
        self.assertEqual(r.status_code, 200)
        self.app.state.copilot_clients.search.assert_awaited_once_with("TEST")
        r = await self.tool("fetch_webpage", {"url": "https://example.com/news"})
        self.assertEqual(r.json()["data"]["content"], "真实正文")
        count = self.app.state.copilot_clients.fetch.await_count
        r = await self.tool("fetch_webpage", {"url": "http://127.0.0.1/admin"})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.app.state.copilot_clients.fetch.await_count, count)

    async def test_trace_reuses_existing_graph_and_result_cache(self):
        await self.begin()
        r = await self.tool("get_event_trace_result", {"event_key": "weibo/hot/event1"})
        self.assertFalse(r.json()["data"]["found"])
        r = await self.tool("trace_event", {"event_key": "weibo/hot/event1"})
        self.assertEqual(r.status_code, 200, r.text)
        a = r.json()["artifact"]
        await asyncio.gather(*list(self.app.state.copilot_jobs.running.values()))
        r = await self.tool("trace_event", {"event_key": "weibo/hot/event1"})
        self.assertEqual(r.json()["artifact"]["id"], a["id"])
        self.app.state.trace_graph.ainvoke.assert_awaited_once()
        call = self.app.state.trace_graph.ainvoke.await_args.args[0]["selected_event"]
        self.assertEqual(call.event.title, self.item["title"])
        result = await self.client.get(
            f"/api/copilot/results/{a['id']}?thread_id={self.thread}"
        )
        self.assertEqual(result.json()["result"]["status"], "partial")
        other = (await self.client.get("/api/copilot/threads")).json()["thread_id"]
        self.assertEqual(
            (
                await self.client.get(
                    f"/api/copilot/results/{a['id']}?thread_id={other}"
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            (
                await self.client.delete(
                    f"/api/copilot/results/{a['id']}?thread_id={self.thread}"
                )
            ).status_code,
            409,
        )

    async def test_opinion_exact_platform_boundary(self):
        for platform in ["douyin", "zhihu", "bilibili", "ithome", "kuaishou"]:
            self.app.state.board_service.boards[platform + "/hot"] = SimpleNamespace(
                snapshot=SimpleNamespace(items=[self.item]),
                updated_at=None,
                failed=False,
            )
            await self.begin({**PAGE, "platform_id": platform})
            for name in ["get_opinion_result", "analyze_public_opinion"]:
                r = await self.tool(name, {"event_key": platform + "/hot/event1"})
                self.assertEqual(r.status_code, 422, r.text)
            await self.client.post(
                "/api/copilot/finish",
                json={
                    "thread_id": self.thread,
                    "request_id": "b" * 32,
                    "history": [],
                    "messages": [],
                },
            )

    async def test_opinion_reuses_saved_lab_report_without_collection(self):
        await self.begin()
        payload = OpinionRequest(
            function_id="public_opinion",
            idempotency_key="lab-test",
            selection=PAGE,
            event={
                "id": "event1",
                "title": self.item["title"],
                "url": self.item["url"],
            },
        )
        task, _ = self.store.create_task(payload)
        self.store.save_report(
            task["id"],
            {"status": "partial", "stats": {"analyzed_count": 2}, "sections": []},
        )
        with patch("app.copilot.api.create_task", new=AsyncMock()) as create:
            r = await self.tool(
                "analyze_public_opinion", {"event_key": "weibo/hot/event1"}
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["data"]["analysis"]["stats"]["analyzed_count"], 2)
            create.assert_not_awaited()

    async def test_new_opinion_calls_existing_task_entry_and_idempotency(self):
        await self.begin()
        with patch(
            "app.copilot.api.create_task",
            new=AsyncMock(return_value={"id": "existing-task"}),
        ) as create:
            first = await self.tool(
                "analyze_public_opinion", {"event_key": "weibo/hot/event1"}
            )
            second = await self.tool(
                "analyze_public_opinion", {"event_key": "weibo/hot/event1"}
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(
                first.json()["artifact"]["id"], second.json()["artifact"]["id"]
            )
            create.assert_awaited_once()
            self.assertEqual(create.await_args.args[0].event.title, self.item["title"])

    async def test_cancel_trace_does_not_delete_report_or_other_task(self):
        entered = asyncio.Event()

        async def slow(*a, **kw):
            entered.set()
            await asyncio.sleep(30)

        self.app.state.trace_graph.ainvoke = slow
        await self.begin()
        r = await self.tool("trace_event", {"event_key": "weibo/hot/event1"})
        a = r.json()["artifact"]
        await entered.wait()
        r = await self.client.delete(
            f"/api/copilot/results/{a['id']}?thread_id={self.thread}"
        )
        self.assertEqual(r.status_code, 200)
        r = await self.client.get(
            f"/api/copilot/results/{a['id']}?thread_id={self.thread}"
        )
        self.assertEqual(r.json()["artifact"]["status"], "cancelled")

    async def test_expired_lease_cannot_overwrite_new_turn(self):
        await self.begin()
        result = await self.client.post(
            "/api/copilot/finish",
            json={
                "thread_id": self.thread,
                "request_id": "wrong",
                "history": [],
                "messages": [{"content": "forged"}],
            },
        )
        self.assertFalse(result.json()["saved"])
        self.assertEqual(
            (await self.client.get("/api/copilot/threads?id=" + self.thread)).json()[
                "messages"
            ],
            [],
        )

    async def test_clear_history_persists_and_preserves_reports(self):
        store = self.app.state.copilot_store
        owner = self.headers["X-Copilot-Owner"]
        state = store.thread(self.thread, owner)["state"]
        state.update(
            history=[{"role": "user", "content": "old"}],
            messages=[{"role": "user", "content": "old"}],
            events={"old": {}},
            active_event="old",
            artifacts=["existing-report"],
        )
        store.save(self.thread, owner, state)
        response = await self.client.delete("/api/copilot/threads?id=" + self.thread)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cleared"])
        self.assertEqual(
            (await self.client.get("/api/copilot/threads?id=" + self.thread)).json()[
                "messages"
            ],
            [],
        )
        state = store.thread(self.thread, owner)["state"]
        self.assertEqual(state["history"], [])
        self.assertEqual(state["events"], {})
        self.assertIsNone(state["active_event"])
        self.assertEqual(state["artifacts"], ["existing-report"])
        self.assertEqual((await self.begin()).json()["history"], [])

    async def test_clear_requires_owner_and_idle_turn(self):
        other = {**self.headers, "X-Copilot-Owner": "c" * 64}
        self.assertEqual(
            (
                await self.client.delete(
                    "/api/copilot/threads?id=" + self.thread, headers=other
                )
            ).status_code,
            404,
        )
        await self.begin()
        self.assertEqual(
            (
                await self.client.delete("/api/copilot/threads?id=" + self.thread)
            ).status_code,
            409,
        )
        await self.client.post(
            "/api/copilot/finish",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "history": [],
                "messages": [],
            },
        )
        self.assertEqual(
            (
                await self.client.delete("/api/copilot/threads?id=" + self.thread)
            ).status_code,
            200,
        )
        response = await self.client.post(
            "/api/copilot/finish",
            json={
                "thread_id": self.thread,
                "request_id": "b" * 32,
                "history": [],
                "messages": [{"role": "user", "content": "late"}],
            },
        )
        self.assertFalse(response.json()["saved"])
        self.assertEqual(
            (await self.client.get("/api/copilot/threads?id=" + self.thread)).json()[
                "messages"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
