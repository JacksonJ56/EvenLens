import asyncio
import json
import time
from datetime import datetime
from urllib.parse import urlsplit

from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import tool

from ..event_trace.clients import public_url, url_key
from .analysis import CommentAnalysis, non_statistical
from .llm import BudgetExceeded, ToolPolicy
from .prompts import RESEARCH
from .schemas import ExternalSource, OverallAssessment, OpinionReport, ResearchOutput, Section


def temporal_context(payload, dataset):
    from chinese_calendar import get_holiday_detail
    from zoneinfo import ZoneInfo
    dates = []
    for post in dataset["posts"]:
        if post.get("published_at"):
            dates.append(("post_published_at", post["published_at"]))
    for key in ("time_start", "time_end"):
        if dataset["stats"].get(key):
            dates.append(("comment_" + key, dataset["stats"][key]))
    calendar = []
    for kind, value in dict.fromkeys(dates):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Chinese public-holiday dates use Asia/Shanghai, not UTC midnight.
            date = timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date() if timestamp.tzinfo else timestamp.date()
            holiday, name = get_holiday_detail(date)
            calendar.append({"date": date.isoformat(), "date_kind": kind, "is_holiday": holiday, "holiday_name": name})
        except (ValueError, NotImplementedError):
            calendar.append({"date": value, "date_kind": kind, "calendar_status": "unsupported_date"})
    return {"hotspot_captured_at": payload.event.captured_at.isoformat() if payload.event.captured_at else None,
            "capture_is_not_occurrence": True, "calendar": calendar,
            "calendar_source": "chinesecalendar：法定节假日安排，非所有传统节日/节气",
            "warning": "帖子/评论日期不能直接代替事件发生日期；节令文化与事件的关联需要外部来源，时间巧合不证明因果。"}


class OpinionResearch:
    def __init__(self, store, dataset_id, provider, model, settings, budget, progress):
        self.store, self.dataset_id, self.provider, self.model = store, dataset_id, provider, model
        self.settings, self.budget, self.progress = settings, budget, progress
        self.analysis = CommentAnalysis(store, dataset_id, model, settings)
        self.dataset = store.dataset(dataset_id)
        self.external, self.read_sources, self.queries = {}, set(), []
        self.stats_read = self.comments_read = False
        self.context_fetches = 0
        self.warnings = []
        self.analysis_lock = asyncio.Lock()
        self.context_deadline = None
        self.interpretations = []

    def context_remaining(self):
        if self.context_deadline is None:
            self.context_deadline = time.monotonic() + self.settings.context_timeout
        self.budget.context_mode = True
        remaining = self.context_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("宏观语境时间预算已用完")
        return remaining

    def limited_comments(self, rows):
        result, size = [], 0
        for row in rows[:25]:
            text = row["content"][:1200]
            if size + len(text.encode()) > 12000:
                break
            size += len(text.encode())
            result.append({k: row[k] for k in ["post_id", "comment_id", "source_rank", "sort_mode", "created_at", "parent_comment_id"]} | {"content": text})
        return {"comments": result, "truncated": len(rows) > len(result)}

    async def investigate(self, payload):
        self.analysis.event_context = {"title": payload.event.title, "summary": (payload.event.summary or "")[:500],
            "platform_id": payload.selection.platform_id, "feed_id": payload.selection.feed_id,
            "notice": "热点标题与摘要只是研究上下文，不能自动当作已证实事实。"}
        @tool
        async def get_dataset_stats() -> dict:
            """首先获取真实评论数据范围、排序、时间、每帖数量和局限性。"""
            self.stats_read = True
            return self.dataset["stats"]

        @tool
        async def sample_comments(post_id: str = "", offset: int = 0, limit: int = 20, comment_ids: list[str] | None = None) -> dict:
            """按原始采集顺序读取有限评论；offset 是保存顺序，不是重新采样。"""
            self.comments_read = True
            rows = self.store.read_comments(self.dataset_id, post_id=post_id or None, ids=comment_ids,
                       offset=max(0, offset), limit=max(1, min(25, limit)))
            return self.limited_comments(rows)

        @tool
        async def search_comments(keyword: str, post_id: str = "") -> dict:
            """在当前数据集做转义的普通文本查询，最多返回25条；不跨事件检索。"""
            return self.limited_comments(self.store.read_comments(self.dataset_id, post_id=post_id or None,
                                         keyword=keyword[:100], limit=25))

        async def analyze(kind, issue=""):
            self.budget.context_mode = False
            if not self.stats_read or not self.comments_read:
                return {"error": "请先查看 get_dataset_stats 和 sample_comments"}
            try:
                async with self.analysis_lock, asyncio.timeout(self.settings.tool_timeout):
                    return await self.analysis.analyze(kind, issue)
            except BudgetExceeded:
                raise
            except Exception:
                from .analysis import TITLES
                section = Section(type=kind, title=TITLES[kind], status="failed", summary="此项评论分析未完成。",
                                  reason="模型请求、结构化输出或工具时间预算失败；未将未完成批次计为统计结果。")
                self.analysis.sections[kind] = section
                return self.analysis.compact(section)

        @tool
        async def extract_discussion_topics() -> dict:
            """分批归纳主题，跨批次归并标签，程序计算真实归属数量和代表评论。"""
            return await analyze("discussion_topics")

        @tool
        async def analyze_emotions() -> dict:
            """按批次分类一级评论情绪，无法判断单列；不等同支持/反对立场。"""
            return await analyze("public_emotions")

        @tool
        async def extract_opinions() -> dict:
            """按评论证据归纳主要观点和理由，不预设正反两方。"""
            return await analyze("opinion_clusters")

        @tool
        async def analyze_stances(issue: str) -> dict:
            """仅对评论中确有的明确议题识别立场；无明确议题不要调用。"""
            return await analyze("stance_analysis", issue)

        @tool
        async def analyze_controversies() -> dict:
            """检验是否有真实观点冲突；不存在时返回不适用，不构造虚假争议。"""
            return await analyze("controversies")

        @tool
        async def analyze_trends() -> dict:
            """只有时间覆盖足够才观察样本变化，不能解释全平台总体趋势。"""
            return await analyze("trends")

        @tool
        async def get_temporal_context() -> dict:
            """返回事件、帖子、评论各自时间；未知日期不替换为今天。节令关联须外部核实。"""
            return temporal_context(payload, self.dataset)

        @tool
        async def search_context(query: str) -> dict:
            """核实背景资料。独立搜索预算；仅返回真实搜索资料，不是事实裁决。"""
            if not self.provider.settings.search_key:
                return {"error": "未配置外部搜索凭据"}
            if len(self.queries) >= self.settings.context_searches:
                return {"error": "宏观背景搜索预算已用完"}
            query = query.strip()[:128]
            if query in self.queries:
                return {"error": "已搜索相同关键词，请使用已有证据"}
            self.queries.append(query)
            self.progress("contextual_research", "正在研究宏观关联")
            try:
                async with asyncio.timeout(self.context_remaining()):
                    hits = await self.provider.search(query)
            except Exception:
                self.warnings.append("宏观背景搜索失败或达到独立时间预算；未将缺失资料视为事实依据。")
                return {"error": "背景搜索失败或超时，请使用已有评论资料结束研究", "sources": []}
            found = []
            for hit in hits[:6]:
                try:
                    url = public_url(hit.url)
                except ValueError:
                    continue
                previous = next((s for s in self.external.values() if url_key(s["url"]) == url_key(url)), None)
                if previous:
                    found.append(previous)
                    continue
                sid = f"context_{len(self.external) + 1}"
                source = {"id": sid, "title": hit.title[:500], "url": url, "published_at": hit.date,
                          "access": "summary", "summary": (hit.snippet or hit.summary)[:1800]}
                self.external[sid] = source
                found.append(source)
            return {"sources": found}

        @tool
        async def fetch_context(source_id: str) -> dict:
            """读取已搜索的背景资料正文；读取失败不能充当已核验全文。"""
            source = self.external.get(source_id)
            if not source or self.context_fetches >= 5:
                return {"error": "来源无效或已达到背景阅读上限"}
            if source_id in self.read_sources:
                return source
            self.context_fetches += 1
            try:
                async with asyncio.timeout(self.context_remaining()):
                    page = await self.provider.fetch(source["url"])
            except Exception:
                return {"error": "背景正文读取失败，仅有搜索摘要"}
            if not page.content.strip():
                return {"error": "未返回正文"}
            source.update(content=page.content[:6000], access="body")
            self.read_sources.add(source_id)
            return source

        @tool
        async def search_historical_topics() -> dict:
            """查询本机已完成的舆情任务；历史样本有限，无记录即为空。"""
            return {"events": self.store.historical(payload.event.title)}

        @tool
        async def compare_information_sources() -> dict:
            """比较已获取公开资料的域名、时间和标题；不推断平台算法或隐藏动机。"""
            return {"sources": [{"id": s["id"], "domain": urlsplit(s["url"]).hostname,
                    "published_at": s["published_at"], "title": s["title"], "access": s["access"]} for s in self.external.values()],
                    "limitation": "标题和发布时间差异不足以证明报道意图或因果关系。"}

        @tool
        async def get_related_events() -> dict:
            """检查现有事件溯源历史可用性；当前模块没有持久化检索，不伪造相关事件。"""
            return {"events": [], "reason": "现有事件溯源没有可复用的历史查询接口，可使用公开搜索补充。"}

        tools = [get_dataset_stats, sample_comments, search_comments, extract_discussion_topics, analyze_emotions,
                 extract_opinions, analyze_stances, analyze_controversies, analyze_trends, get_temporal_context,
                 search_context, fetch_context, search_historical_topics, compare_information_sources, get_related_events]
        agent = create_deep_agent(self.model, tools=tools, name="PublicOpinionAgent", system_prompt=RESEARCH,
            response_format=ToolStrategy(ResearchOutput, handle_errors=False),
            middleware=[ToolPolicy({t.name for t in tools}, self.budget)])
        previous_headroom = self.budget.headroom_tokens, self.budget.headroom_calls
        self.budget.headroom_tokens = min(24000, self.settings.max_tokens // 4)
        self.budget.headroom_calls = 1
        try:
            result = await agent.ainvoke({"messages": [{"role": "user", "content": json.dumps({
                "event": payload.event.model_dump(mode="json"), "selection": payload.selection.model_dump(),
                "dataset_id": self.dataset_id,
            }, ensure_ascii=False)}]}, {"recursion_limit": 45, "max_concurrency": 1})
            output: ResearchOutput = result["structured_response"]
        except BudgetExceeded as error:
            # A growing harness prompt may not fit although compact batch analysis still does.
            # Keep the same budget/headroom and use the existing validated analysis tool;
            # never discard collected comments or increase the user's spending limit.
            topic = self.analysis.sections.get("discussion_topics")
            if topic is None or topic.status == "failed":
                self.progress("public_opinion_analysis", "研究上下文超出剩余预算，正在尝试精简主题分析")
                await get_dataset_stats.ainvoke({})
                await sample_comments.ainvoke({"limit": 3})
                self.analysis.sections.pop("discussion_topics", None)
                await extract_discussion_topics.ainvoke({})
                topic = self.analysis.sections.get("discussion_topics")
            if topic is None or topic.status == "failed":
                raise error
            self.warnings.append("后续 Agent 请求超出剩余预算，已停止扩展研究，仅保留实际完成并验证的分析；"
                                 "必要时采用精简分批主题分析，未提高任务预算。")
            output = ResearchOutput(section_types=list(self.analysis.sections))
        finally:
            self.budget.headroom_tokens, self.budget.headroom_calls = previous_headroom
            self.budget.context_mode = False
        if (not self.stats_read or not self.comments_read or "discussion_topics" not in self.analysis.sections
                or self.analysis.sections["discussion_topics"].status == "failed"):
            raise ValueError("Agent 未完成必要的数据范围、评论和主题检查，未生成可信报告")
        # All sections must originate from an actually executed tool, not the final model prose.
        sections = [self.analysis.sections[t] for t in dict.fromkeys(["discussion_topics", *output.section_types]) if t in self.analysis.sections]
        if not sections:
            sections = list(self.analysis.sections.values())
        insights = []
        for insight in output.contextual_insights:
            from .preparation import normalize
            valid_quotes = [q for q in insight.evidence if q.source_id in insight.source_ids and
                            q.source_id in self.read_sources and
                            normalize(q.excerpt) in normalize(self.external[q.source_id].get("content", ""))]
            if (not insight.source_ids or any(sid not in self.read_sources for sid in insight.source_ids)
                    or {q.source_id for q in valid_quotes} != set(insight.source_ids)):
                self.warnings.append("已移除缺少已读来源或可定位原文摘录的宏观关联。")
                continue
            insight = insight.model_copy(update={"evidence": valid_quotes})
            # Reading an article is not an independent factual verification. Downgrade model claims.
            if insight.classification == "verified_fact":
                insight = insight.model_copy(update={"classification": "supported_inference",
                    "uncertainty": "来源陈述与关联仍需人工核查；非独立事实认定。" + insight.uncertainty})
            insights.append(insight)
        if insights:
            sections.append(Section(type="contextual_insights", title="热点背后的关联", status="completed",
                             summary="以下关联是有来源的研究推断，时间相关性不代表因果。", contextual_insights=insights))
        # Representative comments selected by source order, not fabricated excerpts.
        roots = [c for c in self.analysis.comments if not c["parent_comment_id"]][:6]
        from .schemas import Evidence
        sections.append(Section(type="representative_comments", title="前排评论原文", status="completed",
                         summary="按保存顺序展示的有限原文；不代表全体用户。",
                         evidence=[Evidence(post_id=c["post_id"], comment_id=c["comment_id"]) for c in roots]))
        sources = [ExternalSource.model_validate({k: s[k] for k in ExternalSource.model_fields}) for s in self.external.values()]
        from .assessment import synthesize_assessment
        from .visualization import enrich_report
        from .store import now
        self.progress("overall_assessment", "正在基于已核验证据形成 AI 总体评价")
        report = OpinionReport(task_id="synthesis", dataset_id=self.dataset_id, selection=payload.selection,
            selected_event=payload.event, generated_at=now(), status="partial" if self.warnings or any(s.status in {"failed", "insufficient_data"} for s in sections) else "completed",
            overall_assessment=OverallAssessment(status="unavailable"), stats=self.dataset["stats"], sections=sections,
            posts=self.dataset["posts"], sources=sources, limitations=self.dataset["stats"]["limitations"] + self.warnings, usage={})
        report = enrich_report(report, self.analysis.comments)
        synthesis = await synthesize_assessment(self.model, report, self.analysis.comments, self.store)
        self.interpretations = synthesis.chart_interpretations
        if synthesis.overall_assessment.status == "unavailable":
            self.warnings.append(synthesis.overall_assessment.reason)
        return synthesis.overall_assessment, sections, sources, self.warnings, {"context_searches": len(self.queries), "context_fetches": self.context_fetches}
