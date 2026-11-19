"""No real API credits or platform logins. Exercises the real LangGraph + Deep Agents harness."""
import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from app.event_trace.clients import FetchedPage, SearchHit
from app.event_trace.settings import TraceSettings
from app.public_opinion import api
from app.public_opinion.analysis import CommentAnalysis, batches, comment_ref
from app.public_opinion.collector import identify_post, map_comment, worker_environment
from app.public_opinion.discovery import PostDiscovery
from app.public_opinion.llm import Budget, BudgetExceeded, ToolPolicy
from app.public_opinion.preparation import parse_import, prepare_comments
from app.public_opinion.research import OpinionResearch, temporal_context
from app.public_opinion.schemas import CommentInput, OpinionRequest, Post
from app.public_opinion.settings import OpinionSettings
from app.public_opinion.store import OpinionStore
from app.public_opinion.workflow import OpinionTasks, create_opinion_graph, validate_report

URL = "https://m.weibo.cn/detail/4982041758140155"


def request_data(platform="weibo", dataset=None):
    return OpinionRequest(function_id="public_opinion", idempotency_key="test-request",
        selection=dict(category_id="general", category_name="综合", platform_id=platform, platform_name="测试来源",
                       feed_id="hot", board_id=None, board_name=None),
        event=dict(id="topic_01", title="测试研究主题", url=URL, captured_at="2025-04-04T10:00:00Z"), dataset_id=dataset)


def post():
    return Post(id="4982041758140155", platform_id="weibo", url=URL, title="测试帖子", verification="authorized_import")


def rows(n=7):
    return [CommentInput(platform_id="weibo", post_id=post().id, comment_id=f"c{i}", content="支持！" if i % 2 else "希望提供更充分的信息。",
                         source_rank=i + 1, created_at="2025-04-04T08:00:00Z") for i in range(n)]


class ScriptedModel(BaseChatModel):
    """Deterministic tool-calling fixture; never imported by production modules."""
    model_name: str = "test-fixture"
    _bound: list = PrivateAttr(default_factory=list)
    _calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self):
        return "scripted-opinion-test"

    def bind_tools(self, tools, **kwargs):
        self._bound = tools
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._calls += 1
        system = str(messages[0].content)
        last = messages[-1]
        if "BatchOutput" in system:
            data = json.loads(last.content)
            result = {"applicable": True, "reason": "", "groups": [
                {"label": "中立" if data["task"] == "public_emotions" else "信息透明", "explanation": "希望了解信息",
                 "comment_refs": [c["ref"] for c in data["comments"]] + ["invented-reference"]}]}
            message = AIMessage(content=json.dumps(result, ensure_ascii=False))
        elif "MergeOutput" in system:
            data = json.loads(last.content)
            message = AIMessage(content=json.dumps({"mapping": [{"group_key": g["key"], "canonical_label": "信息透明"} for g in data["groups"]]}))
        elif "ReportSynthesis" in system:
            data = json.loads(last.content)
            refs = [{"post_id": c["post_id"], "comment_id": c["comment_id"]} for c in data["evidence_comments"][:1]]
            message = AIMessage(content=json.dumps({"overall_assessment": {
                "summary": "TEST 样本主要关注信息透明，已有评论强调获得可靠依据。相关讨论应结合有限的数据范围理解；未研究的维度不能擅自解释。",
                "core_judgment": "TEST 先确认公开信息与样本范围，再理解评论观点。", "key_findings": ["TEST 信息公开是已有样本中的关注点。"],
                "section_types": [s["type"] for s in data["sections"]], "evidence": refs},
                "chart_interpretations": [{"chart_id": c["chart_id"], "analysis": "TEST 当前图表应结合已有观点和样本范围解读，不能代表平台全部用户。",
                    "evidence": [ref for p in c["points"] for ref in p["evidence"]][:1]} for c in data["charts"]]}, ensure_ascii=False))
        else:
            tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
            names = [m.name for m in tool_messages]
            discovery = "PostDiscoveryAgent" in system
            if discovery:
                sequence = ["search_web", "fetch_page", "validate_posts", "rank_posts", "DiscoveryChoice"]
                args = [{"query": "测试研究主题 相关讨论"}, {"url": URL}, {"urls": [URL]},
                        {"post_ids": [post().id], "reasons": ["与事件主题匹配"]}, {"post_ids": [post().id], "limitations": []}]
            else:
                sequence = ["get_dataset_stats", "sample_comments", "extract_discussion_topics", "analyze_emotions", "ResearchOutput"]
                args = [{}, {}, {}, {}, {"section_types": ["discussion_topics", "public_emotions"], "contextual_insights": []}]
            index = min(len(tool_messages), len(sequence) - 1)
            message = AIMessage(content="", tool_calls=[{"name": sequence[index], "args": args[index], "id": f"tool_{self._calls}"}])
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)


class Provider:
    settings = TraceSettings(search_key="test-only")

    async def search(self, query):
        return [SearchHit(title="测试帖子", url=URL, snippet="这是测试资料，并非生产新闻。")]

    async def fetch(self, url):
        return FetchedPage(title="测试帖子", content="用于自动化测试的正文，不是生产分析。" * 20)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.settings = OpinionSettings("sqlite:///:memory:")

    def test_order_limits_id_dedup_but_same_text_kept(self):
        source = rows(8)
        source.insert(1, source[0])
        source[3] = source[3].model_copy(update={"content": " \t &amp; \r\n支持！\u200b"})
        prepared, stats = prepare_comments([post()], source, replace(self.settings, per_post=4, max_comments=3))
        self.assertEqual([c.comment_id for c in prepared], ["c0", "c1", "c2"])
        self.assertEqual(stats.prepared_count, 3)
        self.assertEqual(stats.analyzed_count, 0)
        self.assertEqual(stats.input_count, 9)
        self.assertEqual(stats.collected_count, 0)
        self.assertEqual(prepared[2].content, "& \n支持！")
        prepared, _ = prepare_comments([post()], rows(5), self.settings)
        self.assertEqual(len(prepared), 5)
        self.assertTrue(prepared[3].duplicate_text)
        self.assertIn("unknown", stats.sort_modes)

    def test_replies_excluded_from_denominator(self):
        source = rows(2) + [rows(1)[0].model_copy(update={"comment_id": "reply", "parent_comment_id": "c0"})]
        prepared, stats = prepare_comments([post()], source, self.settings)
        self.assertEqual(len(prepared), 3)
        self.assertEqual(stats.prepared_count, 2)
        self.assertEqual(stats.reply_count, 1)
        self.assertEqual(sum(len(b) for b in batches([c.model_dump(mode="json") for c in prepared], 10000)), 2)

    def test_import_strict_platform_and_real_url_mapping(self):
        content = json.dumps({"posts": [post().model_dump(mode="json", exclude={"verification"})],
                              "comments": [r.model_dump(mode="json") for r in rows()]})
        posts, comments = parse_import(content, "json", "weibo")
        self.assertEqual(len(comments), 7)
        with self.assertRaises(ValueError):
            parse_import(content, "json", "zhihu")
        with self.assertRaises(ValueError):
            parse_import(content.replace(URL, "http://127.0.0.1/private"), "json", "weibo")

    def test_csv_import(self):
        content = f"platform_id,post_id,comment_id,content,post_url,source_rank\nweibo,{post().id},csv1,正常评论,{URL},1\n"
        posts, comments = parse_import(content, "csv", "weibo")
        self.assertEqual(comments[0].comment_id, "csv1")
        self.assertEqual(posts[0].url, URL)

    def test_seven_platform_identifiers_and_cross_platform_rejected(self):
        fixtures = {"weibo": URL, "xiaohongshu": "https://www.xiaohongshu.com/explore/1234567890abcdef12345678",
            "douyin": "https://www.douyin.com/video/123456", "kuaishou": "https://www.kuaishou.com/short-video/abc123",
            "bilibili": "https://www.bilibili.com/video/BV1xx411c7mD", "tieba": "https://tieba.baidu.com/p/123456",
            "zhihu": "https://www.zhihu.com/question/100/answer/200"}
        for platform, url in fixtures.items():
            self.assertIsNotNone(identify_post(platform, url))
        self.assertIsNone(identify_post("weibo", "https://weibo.com.evil.org/detail/123"))
        self.assertIsNone(identify_post("zhihu", "https://www.zhihu.com/question/100"))
        self.assertIsNone(identify_post("weibo", "http://localhost/detail/123"))

    def test_collection_mapping_and_unknown_sort(self):
        comment = map_comment({"comment_id": 100, "content": "原文", "create_time": 1743753600000,
                               "parent_comment_id": "0", "comment_like_count": "5"}, post(), 9)
        self.assertEqual(comment.source_rank, 9)
        self.assertEqual(comment.like_count, 5)
        self.assertIsNone(comment.parent_comment_id)
        self.assertEqual(comment.sort_mode, "unknown")

    def test_worker_does_not_inherit_internal_credentials(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-secret", "EVENT_TRACE_LLM_API_KEY": "test-secret",
                                    "PUBLIC_OPINION_DATABASE_URL": "test-secret", "MEDIACRAWLER_COOKIES_WB": "test-cookie"}):
            env = worker_environment()
            self.assertNotIn("DEEPSEEK_API_KEY", env)
            self.assertNotIn("EVENT_TRACE_LLM_API_KEY", env)
            self.assertNotIn("PUBLIC_OPINION_DATABASE_URL", env)
            self.assertNotIn("MEDIACRAWLER_COOKIES_WB", env)

    def test_batch_bytes_and_long_text(self):
        comments = [r.model_copy(update={"content": "长评论" * 2000}).model_dump(mode="json") for r in rows(100)]
        groups = list(batches(comments, 10000))
        self.assertGreater(len(groups), 1)
        self.assertTrue(all(len(b) <= 35 for b in groups))
        self.assertTrue(all(len(c["content"]) <= 1200 for b in groups for c in b))

    def test_budget_enforced_before_model(self):
        budget = Budget(replace(self.settings, max_model_calls=1, max_tokens=10000))
        budget.reserve(["short"], 100)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(["short"], 100)

    def test_temporal_context_uses_sample_year_and_not_capture_date(self):
        context = temporal_context(request_data(), {"posts": [], "stats": {
            "time_start": "2025-04-04T08:00:00Z", "time_end": "2025-04-04T09:00:00Z"}})
        self.assertTrue(any(c["holiday_name"] == "Tomb-sweeping Day" for c in context["calendar"]))
        self.assertTrue(all(c["date"] == "2025-04-04" for c in context["calendar"]))
        unknown = temporal_context(request_data(), {"posts": [], "stats": {}})
        self.assertEqual(unknown["calendar"], [])


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = OpinionSettings(f"sqlite:///{self.directory.name}/test.sqlite")
        self.store = OpinionStore(self.settings.database_url)
        self.payload = request_data()
        prepared, stats = prepare_comments([post()], rows(), self.settings)
        self.dataset = self.store.save_dataset(self.payload, [post()], prepared, stats)
        self.model = ScriptedModel()

    async def asyncTearDown(self):
        self.store.engine.dispose()
        self.directory.cleanup()

    async def test_real_deep_agent_discovery(self):
        stages = []
        discovery = PostDiscovery(Provider(), self.model, self.settings, Budget(self.settings), lambda s, m: stages.append(s))
        posts, warnings, usage = await discovery.discover(self.payload)
        self.assertEqual([p.id for p in posts], [post().id])
        self.assertEqual(usage["discovery_searches"], 1)
        self.assertEqual(usage["discovery_fetches"], 1)
        self.assertIn("post_validation", stages)

    async def test_discovery_budget_and_timeout_errors_are_distinct(self):
        for failure, phrase in [(TimeoutError(), "秒时限"), (BudgetExceeded("test limit"), "预算不足")]:
            with self.subTest(phrase=phrase):
                class FailedModel(ScriptedModel):
                    async def _agenerate(self, *args, **kwargs):
                        raise failure
                discovery = PostDiscovery(Provider(), FailedModel(), self.settings, Budget(self.settings), lambda *a: None)
                with self.assertRaisesRegex(ValueError, phrase):
                    await discovery.discover(self.payload)

    async def test_real_deep_agent_research_counts_and_cache(self):
        research = OpinionResearch(self.store, self.dataset, Provider(), self.model, self.settings, Budget(self.settings), lambda *a: None)
        insight, sections, sources, warnings, usage = await research.investigate(self.payload)
        self.assertIn("信息透明", insight.summary)
        self.assertEqual(sections[0].data[0].count, 7)
        self.assertEqual(sections[0].data[0].percent, 100)
        self.assertEqual(len(sections[0].data[0].evidence), 7)
        self.assertNotIn("invented-reference", str(sections))
        cached = CommentAnalysis(self.store, self.dataset, self.model, self.settings)
        cached.event_context = research.analysis.event_context
        calls = self.model._calls
        await cached.analyze("discussion_topics")
        self.assertEqual(calls, self.model._calls)

    async def test_large_harness_request_falls_back_to_bounded_real_topic_batches(self):
        budget = Budget(self.settings)
        budget.tokens = budget.reserved = 67489
        budget.calls = 11

        class CompactBudgetModel(ScriptedModel):
            async def _agenerate(inner, messages, stop=None, run_manager=None, **kwargs):
                system = str(messages[0].content)
                compact = any(schema in system for schema in ('BatchOutput', 'MergeOutput', 'ReportSynthesis'))
                ticket = budget.reserve(messages if compact else ['x' * 65000], 2500)
                result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                budget.settle(ticket, {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200})
                return result

        research = OpinionResearch(self.store, self.dataset, Provider(), CompactBudgetModel(), self.settings, budget, lambda *a: None)
        assessment, sections, _, warnings, _ = await research.investigate(self.payload)
        self.assertTrue(research.stats_read and research.comments_read)
        self.assertEqual(sections[0].type, 'discussion_topics')
        self.assertEqual(sections[0].sample_size, 7)
        self.assertEqual(assessment.status, 'partial')
        self.assertTrue(assessment.summary)
        self.assertTrue(any('未提高任务预算' in warning for warning in warnings))
        self.assertLess(budget.reserved, self.settings.max_tokens)
        self.assertEqual((budget.headroom_tokens, budget.headroom_calls), (0, 0))

    async def test_compact_fallback_also_stops_when_budget_cannot_fit(self):
        class ExhaustedModel(ScriptedModel):
            async def _agenerate(inner, *args, **kwargs):
                raise BudgetExceeded('TEST budget cannot fit')
        budget = Budget(self.settings)
        research = OpinionResearch(self.store, self.dataset, Provider(), ExhaustedModel(), self.settings, budget, lambda *a: None)
        with self.assertRaisesRegex(BudgetExceeded, 'TEST budget cannot fit'):
            await research.investigate(self.payload)
        self.assertEqual((budget.headroom_tokens, budget.headroom_calls), (0, 0))

    async def test_batched_merge(self):
        settings = replace(self.settings, batch_bytes=400)
        analysis = CommentAnalysis(self.store, self.dataset, self.model, settings)
        result = await analysis.analyze("discussion_topics")
        self.assertEqual(result["data"][0]["count"], 7)
        self.assertEqual(result["sample_size"], 7)

    async def test_import_graph_persists_report_and_no_comment_bodies_in_state(self):
        payload = self.payload.model_copy(update={"dataset_id": self.dataset})
        task, _ = self.store.create_task(payload)
        with patch("app.public_opinion.workflow.make_model", return_value=self.model):
            graph = create_opinion_graph(task["id"], self.store, Provider(), TraceSettings(), self.settings,
                                        Budget(self.settings), lambda *a: None)
            result = await graph.ainvoke({"task_id": task["id"], "request": payload})
        report = self.store.report(task["id"])
        self.assertEqual(report["stats"]["analyzed_count"], 7)
        self.assertEqual(report["selected_event"]["id"], payload.event.id)
        self.assertNotIn("comments", result)
        saved = self.store.get_task(task["id"])["checkpoint"]
        self.assertEqual(saved["dataset_id"], self.dataset)
        self.assertNotIn("raw_content", str(saved))

    async def test_empty_and_inapplicable_analysis(self):
        analysis = CommentAnalysis(self.store, self.dataset, self.model, self.settings)
        result = await analysis.analyze("trends")
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("error", await analysis.analyze("stance_analysis"))

    async def test_partial_batches_do_not_count_unprocessed_comments(self):
        class LimitedModel(ScriptedModel):
            _batches: int = PrivateAttr(default=0)

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                if "BatchOutput" in str(messages[0].content):
                    self._batches += 1
                    if self._batches > 1:
                        raise BudgetExceeded("test budget exhausted")
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        model = LimitedModel()
        payload = self.payload.model_copy(update={"dataset_id": self.dataset})
        task, _ = self.store.create_task(payload)
        with patch("app.public_opinion.workflow.make_model", return_value=model):
            graph = create_opinion_graph(task["id"], self.store, Provider(), TraceSettings(), replace(self.settings, batch_bytes=400),
                                        Budget(self.settings), lambda *a: None)
            await graph.ainvoke({"task_id": task["id"], "request": payload})
        report = self.store.report(task["id"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["stats"]["prepared_count"], 7)
        self.assertLess(report["stats"]["analyzed_count"], 7)
        self.assertGreater(report["stats"]["analyzed_count"], 0)

    async def test_optional_context_search_failure_keeps_comment_analysis(self):
        class ContextModel(ScriptedModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                names = [m.name for m in messages if isinstance(m, ToolMessage)]
                if names and names[-1] == "analyze_emotions":
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                        "name": "search_context", "args": {"query": "核实事件背景"}, "id": "context-test"}]))])
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        class FailedProvider(Provider):
            async def search(self, query):
                raise TimeoutError("upstream unavailable")

        research = OpinionResearch(self.store, self.dataset, FailedProvider(), ContextModel(), self.settings,
                                   Budget(self.settings), lambda *a: None)
        insight, sections, sources, warnings, usage = await research.investigate(self.payload)
        self.assertTrue(any(s.type == "discussion_topics" and s.status == "completed" for s in sections))
        self.assertEqual(sources, [])
        self.assertTrue(any("背景搜索失败" in warning for warning in warnings))

    async def test_hidden_tools_cannot_execute_or_delegate(self):
        policy = ToolPolicy({"search_web"}, Budget(self.settings))
        handler = AsyncMock()
        response = await policy.awrap_tool_call(SimpleNamespace(tool_call={"id": "blocked", "name": "execute"}), handler)
        self.assertIn("未授权", response.content)
        handler.assert_not_awaited()
        await policy.awrap_tool_call(SimpleNamespace(tool_call={"id": "blocked", "name": "task"}), handler)
        handler.assert_not_awaited()

    async def test_cancel_timeout_and_queue_cleanup(self):
        payload = self.payload.model_copy(update={"dataset_id": self.dataset})
        task, _ = self.store.create_task(payload)
        entered = asyncio.Event()

        async def slow(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        runner = OpinionTasks(self.store, Provider(), TraceSettings(), self.settings)
        with patch("app.public_opinion.workflow.create_opinion_graph", return_value=SimpleNamespace(ainvoke=slow)):
            runner.start(task["id"])
            await asyncio.wait_for(entered.wait(), 1)
            await runner.cancel(task["id"])
        self.assertEqual(self.store.get_task(task["id"])["status"], "cancelled")
        self.assertNotIn(task["id"], runner.running)
        runner.settings = replace(self.settings, task_timeout=.01)
        self.store.update_task(task["id"], status="queued")
        with patch("app.public_opinion.workflow.create_opinion_graph", return_value=SimpleNamespace(ainvoke=slow)):
            runner.start(task["id"])
            await asyncio.gather(*list(runner.running.values()))
        self.assertEqual(self.store.get_task(task["id"])["status"], "failed")
        self.assertIn("超时", self.store.get_task(task["id"])["message"])

    async def test_report_validation_rejects_unknown_comment(self):
        from app.public_opinion.schemas import OpinionReport
        prepared, stats = prepare_comments([post()], rows(), self.settings)
        report = OpinionReport(task_id="test", dataset_id=self.dataset, selection=self.payload.selection,
            selected_event=self.payload.event, generated_at=datetime.now(timezone.utc).isoformat(), status="completed",
            insight="测试", stats=stats, posts=[post()], sources=[], limitations=[], usage={}, sections=[{
                "type": "discussion_topics", "title": "测试", "status": "completed", "summary": "测试",
                "data": [{"label": "测试", "evidence": [{"post_id": post().id, "comment_id": "does-not-exist"}]}]}])
        with self.assertRaises(ValueError):
            validate_report(report, self.store)

    async def test_stored_records_survive_new_repository(self):
        task, _ = self.store.create_task(self.payload)
        reopened = OpinionStore(self.settings.database_url)
        self.assertEqual(reopened.get_task(task["id"])["payload"]["event"]["id"], "topic_01")
        self.assertEqual([c["comment_id"] for c in reopened.read_comments(self.dataset)], [f"c{i}" for i in range(7)])
        reopened.engine.dispose()

    async def test_discovery_budgets_are_enforced_in_tool_layer(self):
        class LoopModel(ScriptedModel):
            def _generate(self, messages, **kwargs):
                self._calls += 1
                if self._calls <= 7:
                    msg = AIMessage(content="", tool_calls=[{"name": "search_web", "args": {"query": f"调整查询 {self._calls}"}, "id": str(self._calls)}])
                else:
                    msg = AIMessage(content="", tool_calls=[{"name": "DiscoveryChoice", "args": {"post_ids": [], "limitations": ["不足"]}, "id": "end"}])
                return ChatResult(generations=[ChatGeneration(message=msg)])

            async def _agenerate(self, messages, **kwargs):
                return self._generate(messages, **kwargs)

        discovery = PostDiscovery(Provider(), LoopModel(), replace(self.settings, max_searches=2), Budget(self.settings), lambda *a: None)
        with self.assertRaises(ValueError):
            await discovery.discover(self.payload)
        self.assertEqual(discovery.search_count, 2)

    async def test_idempotence_and_restart_recovery(self):
        one, created = self.store.create_task(self.payload)
        two, created2 = self.store.create_task(self.payload)
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(one["id"], two["id"])
        self.store.update_task(one["id"], status="running", checkpoint={"dataset_id": self.dataset, "collection_done": True})
        self.store.interrupt_running()
        self.assertEqual(self.store.get_task(one["id"])["status"], "interrupted")
        self.assertTrue(self.store.get_task(one["id"])["checkpoint"]["collection_done"])

    async def test_api_validation_import_and_background_pipeline(self):
        app = FastAPI()
        app.include_router(api.router)
        app.state.opinion_store, app.state.opinion_settings = self.store, self.settings
        app.state.trace_settings = TraceSettings(llm_key="test-only", llm_model="test-fixture")
        snapshot = SimpleNamespace(snapshot=SimpleNamespace(items=[{
            "id": self.payload.event.id, "title": "服务端校验后的标题", "url": URL, "rank": 1}]), updated_at=datetime.now(timezone.utc))
        app.state.board_service = SimpleNamespace(boards={"weibo/hot": snapshot, "ithome/hot": snapshot})
        runner = OpinionTasks(self.store, Provider(), app.state.trace_settings, self.settings)
        app.state.opinion_tasks = runner
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/public-opinion/capabilities")
            self.assertTrue(response.json()["platforms"]["weibo"]["supported"])
            self.assertFalse(response.json()["platforms"]["weibo"]["collector_ready"])
            blocked = await client.post("/api/public-opinion/tasks", json=request_data("ithome").model_dump(mode="json"))
            self.assertEqual(blocked.status_code, 422)
            config = await client.post("/api/public-opinion/tasks", json=self.payload.model_dump(mode="json"))
            self.assertEqual(config.status_code, 503)
            with patch.object(OpinionSettings, "collector_status", return_value=(True, "configured")), \
                 patch("app.public_opinion.api.MediaCrawlerAdapter.preflight", new=AsyncMock(side_effect=ValueError("Chromium 不可用"))):
                app.state.opinion_sessions = SimpleNamespace(require_verified=AsyncMock())
                # Search is checked independently; configure it so this exercises actual runtime admission.
                app.state.trace_settings = replace(app.state.trace_settings, search_key="test-only")
                unavailable = await client.post("/api/public-opinion/tasks", json=self.payload.model_dump(mode="json"))
                self.assertEqual(unavailable.status_code, 503)
                self.assertIn("Chromium", unavailable.text)
            content = json.dumps({"posts": [post().model_dump(mode="json", exclude={"verification"})], "comments": [r.model_dump(mode="json") for r in rows()]})
            imported = await client.post("/api/public-opinion/datasets/import", json={"selection": self.payload.selection.model_dump(),
                "event": self.payload.event.model_dump(mode="json"), "content": content, "format": "json", "authorized": True})
            self.assertEqual(imported.status_code, 201, imported.text)
            request = self.payload.model_copy(update={"dataset_id": imported.json()["dataset_id"]})
            with patch("app.public_opinion.workflow.make_model", return_value=self.model):
                started = await client.post("/api/public-opinion/tasks", json=request.model_dump(mode="json"))
                self.assertEqual(started.status_code, 202, started.text)
                task_id = started.json()["id"]
                await asyncio.gather(*list(runner.running.values()))
            status = await client.get(f"/api/public-opinion/tasks/{task_id}")
            self.assertEqual(status.json()["status"], "completed", status.text)
            report = await client.get(f"/api/public-opinion/tasks/{task_id}/report")
            self.assertEqual(report.status_code, 200)
            self.assertEqual(report.json()["selected_event"]["title"], "服务端校验后的标题")
            comment = await client.get(f"/api/public-opinion/tasks/{task_id}/comments", params={"post_id": post().id, "comment_id": "c0"})
            self.assertEqual(comment.json()["comment_id"], "c0")
            request = request.model_copy(update={"event": request.event.model_copy(update={"id": "old-event"})})
            mismatch = await client.post("/api/public-opinion/tasks", json=request.model_dump(mode="json"))
            self.assertEqual(mismatch.status_code, 409)
