import asyncio
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TypedDict
from urllib.parse import urlsplit
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from . import prompts
from .clients import ProviderError, TraceClients, UnsafeURL, public_url, url_key
from .schemas import (
    Evaluation, EventTraceRequest, EventTraceResponse, EvidenceSource, Extraction,
    SearchPlan, TimelineEvent,
)
from .settings import TraceSettings
from .timeline import chronological_key, evidence_text, validate_timeline


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    title: str
    published_at: str | None = None
    site_name: str | None = None
    snippet: str = ""
    summary: str = ""
    body: str = ""
    authority: int = -1
    score: float = 0
    original_link: bool = False
    fetch_status: str = "not_attempted"
    fetch_error: str | None = None

    def texts(self) -> dict[str, str]:
        return {kind: value for kind in ("body", "snippet", "summary") if (value := getattr(self, kind))}


class EventTraceState(TypedDict, total=False):
    selected_event: EventTraceRequest
    event_context: dict
    plan: SearchPlan
    pending_queries: list[str]
    search_queries: list[list[str]]
    search_round: int
    sources: dict[str, Source]
    fetched_count: int
    fetch_unavailable: bool
    evaluation: Evaluation
    extraction: Extraction
    timeline: list[TimelineEvent]
    missing: list[str]
    warnings: list[str]
    response: EventTraceResponse


def clean_queries(values: list[str], earlier: list[list[str]], limit: int) -> list[str]:
    key = lambda value: evidence_text(value).casefold()
    seen = {key(query) for batch in earlier for query in batch}
    new = []
    for value in values:
        token = key(value)
        if token and token not in seen:
            seen.add(token)
            new.append(evidence_text(value))
        if len(new) >= limit:
            break
    return new


def published_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if timestamp.tzinfo else None


def source_rank(source: Source):
    return source.original_link, source.authority >= 3, source.score, source.authority


def create_graph(clients: TraceClients, settings: TraceSettings):
    async def limited(items, call):
        slots = asyncio.Semaphore(settings.parallel)

        async def one(item):
            async with slots:
                return await call(item)

        return await asyncio.gather(*(one(item) for item in items), return_exceptions=True)

    def prepare_event_node(state: EventTraceState) -> dict:
        request = state["selected_event"]
        event = request.event.model_dump(mode="json")
        sources = {}
        warnings = []
        if event["url"]:
            try:
                url = public_url(event["url"])
                sources[url_key(url)] = Source(
                    id="source_001", url=url, title=request.event.title, original_link=True,
                )
                event["url"] = url
            except UnsafeURL:
                event["url"] = None
                warnings.append("已忽略不符合公网规则的热点原始链接")
        return {
            "event_context": {"selection": request.selection.model_dump(mode="json"), "event": event},
            "search_round": 0, "search_queries": [], "sources": sources, "fetched_count": 0,
            "warnings": warnings, "missing": [],
        }

    async def plan_search_node(state: EventTraceState) -> dict:
        plan = await clients.structured(prompts.PLAN, state["event_context"], SearchPlan)
        return {"plan": plan, "pending_queries": clean_queries(plan.queries, [], settings.max_queries)}

    async def search_node(state: EventTraceState) -> dict:
        queries = state["pending_queries"]
        results = await limited(queries, clients.search)
        sources = state["sources"].copy()
        warnings = state["warnings"].copy()
        errors = []
        hits = 0
        for result in results:
            if isinstance(result, ProviderError):
                errors.append(result)
                continue
            if isinstance(result, BaseException):
                raise result
            hits += len(result)
            for hit in result:
                try:
                    url = public_url(hit.url)
                except UnsafeURL:
                    continue
                key = url_key(url)
                prior = sources.get(key)
                if prior is None:
                    prior = Source(id=f"source_{len(sources) + 1:03}", url=url, title=(hit.title.strip() or urlsplit(url).hostname or url)[:400])
                sources[key] = replace(
                    prior, published_at=prior.published_at or published_date(hit.date),
                    site_name=prior.site_name or (hit.site_name[:100] if hit.site_name else None),
                    snippet=prior.snippet or evidence_text(hit.snippet[:1000]),
                    summary=prior.summary or evidence_text(hit.summary[:1600]),
                    authority=max(prior.authority, hit.authority), score=max(prior.score, hit.rerank_score),
                )
        if errors and len(errors) == len(queries) and (not state["search_round"] or not sources):
            raise errors[0]
        if errors:
            warnings.extend(str(error) for error in errors)
        if not hits and not errors:
            warnings.append(f'第 {state["search_round"] + 1} 轮公开搜索未返回匹配结果')
        return {
            "search_round": state["search_round"] + 1, "search_queries": [*state["search_queries"], queries],
            "sources": sources, "warnings": list(dict.fromkeys(warnings)), "pending_queries": [],
        }

    async def fetch_node(state: EventTraceState) -> dict:
        if state.get("fetch_unavailable"):
            return {}
        remaining = settings.max_fetch - state["fetched_count"]
        round_limit = remaining if state["search_round"] == settings.max_rounds else math.ceil(settings.max_fetch / settings.max_rounds)
        candidates = sorted(
            ((key, source) for key, source in state["sources"].items() if source.fetch_status == "not_attempted"),
            key=lambda item: source_rank(item[1]), reverse=True,
        )[:min(remaining, round_limit)]
        if not candidates:
            return {}
        results = await limited(candidates, lambda item: clients.fetch(item[1].url))
        sources = state["sources"].copy()
        warnings = state["warnings"].copy()
        unavailable = False
        for (key, source), result in zip(candidates, results):
            if isinstance(result, UnsafeURL):
                sources[key] = replace(source, fetch_status="blocked", fetch_error=str(result))
            elif isinstance(result, ProviderError):
                sources[key] = replace(source, fetch_status="failed", fetch_error=str(result))
                warnings.append(str(result))
                unavailable = unavailable or result.status in {401, 402}
            elif isinstance(result, BaseException):
                raise result
            else:
                sources[key] = replace(
                    source, title=(result.title.strip() or source.title)[:400],
                    body=evidence_text(result.content[:6500]), fetch_status="fetched",
                )
        return {"sources": sources, "fetched_count": state["fetched_count"] + len(candidates),
                "warnings": list(dict.fromkeys(warnings)), "fetch_unavailable": unavailable}

    def source_packet(state: EventTraceState) -> list[dict]:
        sources = [source for source in state["sources"].values() if source.texts() and source.fetch_status != "blocked"]
        # Include fetched pages and the highest ranked remaining search results, within model context limits.
        ordered = sorted(sources, key=lambda item: (bool(item.body), source_rank(item)), reverse=True)[:16]
        return [{
            "id": item.id, "url": item.url, "title": item.title, "published_at": item.published_at,
            **item.texts(),
        } for item in ordered]

    async def evaluate_node(state: EventTraceState) -> dict:
        sources = source_packet(state)
        evaluation = await clients.structured(prompts.EVALUATE, {
            "event_context": state["event_context"], "plan": state["plan"].model_dump(),
            "earlier_queries": state["search_queries"], "sources": sources,
        }, Evaluation)
        return {"evaluation": evaluation,
                "pending_queries": clean_queries(evaluation.next_queries, state["search_queries"], settings.max_queries)}

    def after_evaluate(state: EventTraceState) -> str:
        evaluation = state["evaluation"]
        enough = evaluation.sufficient and evaluation.resolved and evaluation.subject and source_packet(state)
        if not enough and state["pending_queries"] and state["search_round"] < settings.max_rounds:
            return "search_node"
        return "extract_node"

    async def extract_node(state: EventTraceState) -> dict:
        evaluation = state["evaluation"]
        missing = list(evaluation.missing_aspects)
        if not evaluation.resolved or not evaluation.subject:
            missing.append("公开资料不足，无法确认热点指向")
            return {"extraction": Extraction(events=[]), "missing": missing}
        sources = source_packet(state)
        if not sources:
            missing.append("没有取得可用于引用的来源正文或检索摘要")
            return {"extraction": Extraction(events=[]), "missing": missing}
        output = await clients.structured(prompts.EXTRACT, {
            "event_context": state["event_context"], "subject": evaluation.subject,
            "known_gaps": missing, "sources": sources,
        }, Extraction)
        return {"extraction": output, "missing": [*missing, *output.missing_aspects]}

    def validate_node(state: EventTraceState) -> dict:
        packet = source_packet(state)
        texts = {source["id"]: source for source in packet}
        publication_dates = {source["id"]: source["published_at"] for source in packet if source["published_at"]}
        timeline, dropped, conflict = validate_timeline(state["extraction"].events, texts, publication_dates)
        missing = state["missing"].copy()
        warnings = state["warnings"].copy()
        if dropped:
            warnings.append("已剔除找不到原文对应位置的引用或事件节点")
            missing.append("有候选内容缺少可复查的引文")
        if conflict:
            missing.append("同一节点的发生时间存在来源冲突")
        if any(not any(quote.kind == "body" for quote in event.evidence) for event in timeline):
            missing.append("部分节点仅有搜索片段或摘要支持，缺少可核对正文")
        if not timeline:
            missing.append("尚未找到可验证的时间线节点")
        return {"timeline": timeline, "missing": missing, "warnings": warnings}

    def sort_node(state: EventTraceState) -> dict:
        timeline = sorted(state["timeline"], key=chronological_key)
        evaluation = state["evaluation"]
        subject = evaluation.subject if evaluation.resolved else None
        missing = list(dict.fromkeys(state["missing"]))
        if not evaluation.sufficient and not missing:
            missing.append(evaluation.reason)
        warnings = state["warnings"].copy()
        if (not evaluation.sufficient or not subject) and state["search_round"] >= settings.max_rounds:
            warnings.append("已达到本次调查的搜索轮数上限")
        request = state["selected_event"]
        completed = bool(subject and evaluation.sufficient and timeline and not missing)
        sources = [EvidenceSource(
            id=source.id, url=source.url, title=source.title, published_at=source.published_at, site_name=source.site_name,
            access="body" if source.body else "summary" if source.snippet or source.summary else "unavailable",
            fetch_status=source.fetch_status, fetch_error=source.fetch_error,
        ) for source in state["sources"].values() if source.fetch_status != "blocked"]
        return {"response": EventTraceResponse(
            trace_id=f"trace_{uuid4().hex}", selection=request.selection, selected_event=request.event,
            status="completed" if completed else "partial",
            subject=subject, search_rounds=state["search_round"], search_queries=state["search_queries"],
            suggested_queries=[] if completed else state["pending_queries"],
            timeline=timeline, sources=sources, missing_aspects=missing, warnings=list(dict.fromkeys(warnings)),
        )}

    graph = StateGraph(EventTraceState)
    nodes = [prepare_event_node, plan_search_node, search_node, fetch_node, evaluate_node, extract_node, validate_node, sort_node]
    for node in nodes:
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "prepare_event_node")
    graph.add_edge("prepare_event_node", "plan_search_node")
    graph.add_edge("plan_search_node", "search_node")
    graph.add_edge("search_node", "fetch_node")
    graph.add_edge("fetch_node", "evaluate_node")
    graph.add_conditional_edges("evaluate_node", after_evaluate, ["search_node", "extract_node"])
    graph.add_edge("extract_node", "validate_node")
    graph.add_edge("validate_node", "sort_node")
    graph.add_edge("sort_node", END)
    return graph.compile()
