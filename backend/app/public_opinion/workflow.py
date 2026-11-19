import asyncio
import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..event_trace.clients import ProviderError
from .collector import MediaCrawlerAdapter
from .discovery import PostDiscovery
from .post_reader import AuthenticatedPostReader
from .llm import Budget, make_model
from .preparation import prepare_comments
from .research import OpinionResearch
from .schemas import DatasetStats, OpinionReport, OpinionRequest, Post
from .store import binding, now

logger = logging.getLogger("uvicorn.error")


class OpinionState(TypedDict, total=False):
    task_id: str
    request: OpinionRequest
    posts: list[dict]
    dataset_id: str
    discovery_done: bool
    collection_done: bool
    preparation_done: bool
    research_done: bool
    research: dict
    warnings: list[str]
    usage: dict[str, int]
    partial: bool
    discovery_diagnostics: dict


def validate_report(report: OpinionReport, store):
    dataset = store.dataset(report.dataset_id)
    if not dataset or dataset["binding"] != binding(OpinionRequest(function_id="public_opinion", selection=report.selection,
            event=report.selected_event, idempotency_key="validation")):
        raise ValueError("报告与热点选择不匹配")
    comments = store.read_comments(report.dataset_id)
    roots = {(c["post_id"], c["comment_id"]) for c in comments if not c["parent_comment_id"]}
    source_ids = {s.id for s in report.sources}
    report.stats = DatasetStats.model_validate(dataset["stats"])
    analyzed = set()
    for section in report.sections:
        sample = {(e.post_id, e.comment_id) for e in section.analyzed_sample}
        if not sample <= roots:
            raise ValueError("报告分析样本包含不存在的评论")
        if section.type in {"discussion_topics", "public_emotions", "opinion_clusters", "stance_analysis", "controversies"}:
            analyzed |= sample
        for evidence in section.evidence:
            if (evidence.post_id, evidence.comment_id) not in roots:
                raise ValueError("报告包含不存在的评论引用")
        used = set()
        for group in section.data:
            refs = {(e.post_id, e.comment_id) for e in group.evidence}
            denominator = sample if section.type != "trends" else roots
            if not refs <= denominator or (section.type != "discussion_topics" and used & refs):
                raise ValueError("报告评论归属无效或重复计数")
            used |= refs
            group.count = len(refs)
            group.percent = round(len(refs) / len(denominator) * 100, 1) if denominator else None
        if section.sample_size is not None:
            section.sample_size = len(roots) if section.type == "trends" else len(sample)
        for insight in section.contextual_insights:
            if not set(insight.source_ids) <= source_ids:
                raise ValueError("宏观洞察引用不存在的来源")
            for quote in insight.evidence:
                source = store.source(report.task_id, quote.source_id)
                from .preparation import normalize
                if not source or normalize(quote.excerpt) not in normalize(source.get("content", "")):
                    raise ValueError("宏观来源摘录不能在保存的正文中定位")
    report.stats.analyzed_count = len(analyzed)
    if not analyzed:
        raise ValueError("尚无实际完成的语义分析批次，未生成分析报告")
    if len(analyzed) < report.stats.prepared_count:
        report.status = "partial"
        report.limitations.append(f"保留 {report.stats.prepared_count} 条有效一级评论，实际完成语义分析 {len(analyzed)} 条；未处理记录不计入分析比例。")
    from .visualization import enrich_report
    report = enrich_report(report, comments)
    assessment = report.overall_assessment
    if assessment.status in {"completed", "partial"}:
        if (not assessment.summary.strip() or not assessment.evidence
                or not {(r.post_id, r.comment_id) for r in assessment.evidence} <= roots
                or not set(assessment.source_ids) <= source_ids
                or not set(assessment.section_types) <= {section.type for section in report.sections if section.status in {"completed", "insufficient_data"}}):
            raise ValueError("总体评价引用与已完成研究不匹配")
    chart_map = {chart.id: chart for chart in report.charts}
    for interpretation in report.chart_interpretations:
        chart = chart_map.get(interpretation.chart_id)
        if chart is None or not set(interpretation.source_ids) <= source_ids:
            raise ValueError("图表解读关联无效")
        allowed = {(r.post_id, r.comment_id) for point in chart.points for r in point.evidence}
        if not {(r.post_id, r.comment_id) for r in interpretation.evidence} <= allowed:
            raise ValueError("图表解读引用不属于当前图表")
    return report


def create_opinion_graph(task_id, store, provider, trace_settings, settings, budget, progress):
    model = make_model(trace_settings, settings, budget)

    def checkpoint(state, **changes):
        output = {**state, **changes}
        store.update_task(task_id, checkpoint={k: v for k, v in output.items() if k not in {"request", "task_id"}},
                          usage={**output.get("usage", {}), **budget.snapshot()})
        return changes

    async def post_discovery(state: OpinionState):
        if state.get("discovery_done"):
            return {}
        payload = state["request"]
        if payload.dataset_id:
            dataset = store.dataset(payload.dataset_id)
            return checkpoint(state, posts=dataset["posts"], dataset_id=payload.dataset_id, discovery_done=True,
                              collection_done=True, warnings=["本次使用用户声明已获授权的导入评论；未运行帖子搜索或在线采集。"])
        progress("post_discovery", "正在发现相关帖子")
        def save_diagnostic(value):
            saved = store.get_task(task_id)["checkpoint"]
            store.update_task(task_id, checkpoint={**saved, "discovery_diagnostics": value})
        discovery = PostDiscovery(provider, model, settings, budget, progress, diagnostic=save_diagnostic,
                                  reader=AuthenticatedPostReader(settings))
        posts, warnings, usage = await discovery.discover(payload)
        return checkpoint(state, posts=[p.model_dump(mode="json") for p in posts], warnings=warnings,
                          usage=usage, discovery_done=True, discovery_diagnostics=discovery.diagnostics())

    async def comment_collection(state: OpinionState):
        if state.get("collection_done"):
            return {}
        progress("comment_collection", "正在采集评论")
        posts = [Post.model_validate(p) for p in state["posts"]]
        rows, warnings = await MediaCrawlerAdapter(settings).collect(posts)
        # Keep bodies only in the dataset store; never in LangGraph checkpoint state.
        prepared, stats = prepare_comments(posts, rows, settings)
        dataset_id = store.save_dataset(state["request"], posts, prepared, stats)
        return checkpoint(state, dataset_id=dataset_id, collection_done=True, partial=bool(warnings),
                          warnings=state.get("warnings", []) + warnings)

    async def comment_preparation(state: OpinionState):
        if state.get("preparation_done"):
            return {}
        progress("comment_preparation", "正在整理评论数据")
        dataset = store.dataset(state["dataset_id"])
        if not dataset or not dataset["stats"]["prepared_count"]:
            raise ValueError("当前数据集没有可分析的有效一级评论")
        return checkpoint(state, preparation_done=True)

    async def public_opinion_analysis(state: OpinionState):
        if state.get("research_done"):
            return {}
        progress("public_opinion_analysis", "正在分析公众讨论")
        research = OpinionResearch(store, state["dataset_id"], provider, model, settings, budget, progress)
        assessment, sections, sources, warnings, usage = await research.investigate(state["request"])
        store.save_sources(task_id, research.external)
        return checkpoint(state, research_done=True, partial=state.get("partial", False) or bool(warnings), research={"overall_assessment": assessment.model_dump(),
            "chart_interpretations": [value.model_dump() for value in research.interpretations],
            "sections": [s.model_dump() for s in sections], "sources": [s.model_dump() for s in sources]},
            warnings=state.get("warnings", []) + warnings, usage={**state.get("usage", {}), **usage})

    async def report_validation(state: OpinionState):
        progress("report_validation", "正在核查分析依据")
        dataset, research = store.dataset(state["dataset_id"]), state["research"]
        report = OpinionReport(task_id=task_id, dataset_id=state["dataset_id"], selection=state["request"].selection,
            selected_event=state["request"].event, generated_at=now(),
            status="partial" if state.get("partial") or any(s["status"] in {"failed", "insufficient_data"} for s in research["sections"]) else "completed",
            stats=dataset["stats"], posts=dataset["posts"], limitations=dataset["stats"]["limitations"] + state.get("warnings", []),
            usage={**state.get("usage", {}), **budget.snapshot()}, **research)
        report = validate_report(report, store)
        progress("report_generation", "正在生成研究报告")
        store.save_report(task_id, report.model_dump(mode="json"))
        return {"usage": report.usage}

    builder = StateGraph(OpinionState)
    nodes = [post_discovery, comment_collection, comment_preparation, public_opinion_analysis, report_validation]
    for node in nodes:
        builder.add_node(node.__name__, node)
    builder.add_edge(START, nodes[0].__name__)
    for a, b in zip(nodes, nodes[1:]):
        builder.add_edge(a.__name__, b.__name__)
    builder.add_edge(nodes[-1].__name__, END)
    return builder.compile()


class OpinionTasks:
    """Single-worker-process task runner with persisted stage checkpoints and bounded admission."""
    def __init__(self, store, provider, trace_settings, settings):
        self.store, self.provider, self.trace_settings, self.settings = store, provider, trace_settings, settings
        self.running = {}
        self.slots = asyncio.Semaphore(2)
        store.interrupt_running()

    def progress(self, task_id, stage, message):
        self.store.record_event(task_id, stage, message)
        self.store.update_task(task_id, status="running", stage=stage, message=message)

    def start(self, task_id):
        if task_id in self.running:
            return
        if len(self.running) >= 10:
            raise ValueError("舆情任务队列已满，请稍后重试")
        self.running[task_id] = asyncio.create_task(self.execute(task_id))

    async def execute(self, task_id):
        budget = Budget(self.settings, lambda usage: self.store.update_task(task_id, usage=usage))
        try:
            async with asyncio.timeout(self.settings.task_timeout), self.slots:
                task = self.store.get_task(task_id)
                saved_usage = task.get("usage") or {}
                budget.calls = saved_usage.get("model_calls", 0)
                budget.settled_calls = saved_usage.get("settled_model_calls", 0)
                budget.reserved = saved_usage.get("reserved_token_upper_bound", 0)
                budget.context_reserved = saved_usage.get("context_reserved_token_upper_bound", 0)
                budget.tokens = saved_usage.get("reported_tokens", 0)
                budget.input_tokens = saved_usage.get("input_tokens", 0)
                budget.output_tokens = saved_usage.get("output_tokens", 0)
                budget.tool_calls = saved_usage.get("tool_calls", 0)
                self.progress(task_id, "starting", "正在启动舆情任务")
                graph = create_opinion_graph(task_id, self.store, self.provider, self.trace_settings, self.settings, budget,
                          lambda stage, message: self.progress(task_id, stage, message))
                await graph.ainvoke({**task["checkpoint"], "task_id": task_id,
                                    "request": OpinionRequest.model_validate(task["payload"])}, {"recursion_limit": 12})
                report = self.store.report(task_id)
                self.store.update_task(task_id, status=report["status"], stage="finished", message="研究报告已生成")
        except asyncio.CancelledError:
            current = self.store.get_task(task_id)
            if current["status"] != "interrupted":
                self.store.update_task(task_id, status="cancelled", message="任务已取消")
        except TimeoutError:
            self.store.update_task(task_id, status="failed", message="舆情任务超时，可恢复已完成的数据阶段后重试")
        except (ValueError, ProviderError) as error:
            self.store.update_task(task_id, status="failed", message=str(error)[:1500])
        except Exception as error:
            # Never echo provider bodies, cookies, prompts or headers into public errors/logs.
            logger.warning("公众舆情任务 %s 失败：%s", task_id, type(error).__name__)
            from .llm import BudgetExceeded
            message = str(error) if isinstance(error, BudgetExceeded) else "模型工具调用、结构化输出或采集服务失败，请核对模型能力及配置后重试"
            self.store.update_task(task_id, status="failed", message=message[:1500])
        finally:
            self.store.update_task(task_id, usage=budget.snapshot())
            self.running.pop(task_id, None)

    async def cancel(self, task_id):
        runner = self.running.get(task_id)
        if runner:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
            self.running.pop(task_id, None)
        self.store.update_task(task_id, status="cancelled", message="任务已取消")

    async def close(self):
        runners = list(self.running.items())
        for task_id, runner in runners:
            self.store.update_task(task_id, status="interrupted", message="服务关闭，任务可恢复")
            runner.cancel()
        await asyncio.gather(*(runner for _, runner in runners), return_exceptions=True)
        self.store.engine.dispose()
