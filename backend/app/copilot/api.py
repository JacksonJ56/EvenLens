"""Authenticated local bridge. Only Next.js holds the service credential.

All event identities originate in real BoardService snapshots. Models only see
opaque event keys; URLs/titles in browser requests cannot start arbitrary jobs.
"""

import asyncio
import hashlib
import hmac
import json
import os
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..event_trace.api import canonical_event, trace_cache_key
from ..event_trace.schemas import EventTraceRequest
from ..event_trace.clients import ProviderError, UnsafeURL, public_url
from ..public_opinion.api import create_task
from ..public_opinion.schemas import OpinionRequest
from ..public_opinion.store import tasks, reports
from .store import CopilotStore

router = APIRouter(prefix="/api/copilot", tags=["copilot-internal"])
OPINION_PLATFORMS = {"weibo", "xiaohongshu", "tieba"}


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Query(Wire):
    category_id: str = Field(max_length=80)
    category_name: str = Field(max_length=120)
    platform_id: str = Field(max_length=80)
    platform_name: str = Field(max_length=120)
    feed_id: str = Field(max_length=80)
    board_id: str | None = None
    board_name: str | None = None


class Reference(Wire):
    category_id: str = Field(max_length=80)
    platform_id: str = Field(max_length=80)
    feed_id: str = Field(max_length=80)
    id: str = Field(max_length=120)


class Begin(Wire):
    thread_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^[a-f0-9-]{32,36}$")
    page: Query
    reference: Reference | None = None
    reference_page: Query | None = None
    catalog: list[Query] = Field(default_factory=list, max_length=150)
    selected_event_id: str | None = Field(default=None, max_length=120)
    mode: Literal["live", "mock"] = "live"


class Finish(Wire):
    thread_id: str
    request_id: str
    history: list[dict] = Field(max_length=160)
    messages: list[dict] = Field(max_length=80)


class ToolArgs(Wire):
    event_key: str | None = Field(default=None, max_length=500)
    query: str | None = Field(default=None, min_length=1, max_length=128)
    platform_id: str | None = Field(default=None, max_length=80)
    feed_id: str | None = Field(default=None, max_length=80)
    url: str | None = Field(default=None, max_length=8192)
    refresh: bool = False


class ToolCall(Wire):
    thread_id: str
    request_id: str
    name: Literal[
        "search_hotspots",
        "get_hotspot_detail",
        "web_search",
        "fetch_webpage",
        "get_event_trace_result",
        "trace_event",
        "get_opinion_result",
        "analyze_public_opinion",
    ]
    args: ToolArgs


def guard(request):
    key = (
        os.getenv("COPILOT_SERVICE_TOKEN")
        or hashlib.sha256(
            (request.app.state.trace_settings.llm_key + "\nEventLens Copilot").encode()
        ).hexdigest()
    )
    supplied = request.headers.get("x-eventlens-copilot", "")
    owner = request.headers.get("x-copilot-owner", "")
    if (
        not request.app.state.trace_settings.llm_key
        and not os.getenv("COPILOT_SERVICE_TOKEN")
    ) or not hmac.compare_digest(key, supplied):
        raise HTTPException(403, "Copilot 服务凭据无效")
    import re

    if not re.fullmatch("[a-f0-9]{64}", owner):
        raise HTTPException(403, "会话归属凭据无效")
    return owner


def owned(request, identifier):
    owner = guard(request)
    row = request.app.state.copilot_store.thread(identifier, owner)
    if not row:
        raise HTTPException(404, "会话不存在或不属于当前浏览器")
    return owner, row


def event_record(query, item, entry):
    key = f"{query.platform_id}/{query.feed_id}/{item['id']}"
    return key, {
        "selection": query.model_dump(),
        "event": {
            "id": item["id"],
            "title": item["title"][:1000],
            "url": item.get("url") or None,
            "summary": item.get("preview", {}).get("summary"),
            "rank": item.get("rank"),
            "captured_at": jsonable_encoder(entry.updated_at),
        },
    }


def brief(key, record):
    return {
        "event_key": key,
        **record["event"],
        "summary": (record["event"].get("summary") or "")[:250],
        "platform_id": record["selection"]["platform_id"],
        "feed_id": record["selection"]["feed_id"],
    }


async def board(request, platform, feed):
    state = request.app.state
    key = platform + "/" + feed
    entry = state.board_service.boards.get(key)
    if entry is None:
        raise HTTPException(404, "该榜单尚未接入")
    if entry.snapshot is None:
        await state.board_service.refresh(key)
    if entry.snapshot is None:
        raise HTTPException(503, "榜单暂不可用，请刷新重试")
    return entry


@router.get("/threads")
async def thread(request: Request, id: str | None = None):
    owner = guard(request)
    store = request.app.state.copilot_store
    row = store.thread(id, owner) if id else store.create_thread(owner)
    if not row:
        raise HTTPException(404, "会话不存在或不属于当前浏览器")
    return {"thread_id": row["id"], "messages": row["state"]["messages"]}


@router.delete("/threads")
async def clear_thread_history(request: Request, id: str):
    owner, _ = owned(request, id)
    if not request.app.state.copilot_store.clear_history(id, owner):
        raise HTTPException(409, "当前对话仍在处理，请等待回答结束后再清空")
    return {"cleared": True, "thread_id": id}


@router.post("/begin")
async def begin(payload: Begin, request: Request):
    owner, row = owned(request, payload.thread_id)
    store = request.app.state.copilot_store
    if not store.acquire(row["id"], owner, payload.request_id):
        raise HTTPException(409, "当前会话已有回答正在生成")
    try:
        state = row["state"]
        state["catalog"] = {
            q.platform_id + "/" + q.feed_id: q.model_dump()
            for q in [*payload.catalog, payload.page]
        }
        current = []
        warning = None
        if payload.mode == "mock":
            warning = "页面为演示榜单，不把页面模拟标题作为真实热点；请检索真实资料。"
        else:
            try:
                entry = await board(
                    request, payload.page.platform_id, payload.page.feed_id
                )
                for item in entry.snapshot.items[:30]:
                    key, record = event_record(payload.page, item, entry)
                    state["events"][key] = record
                    # Keep the page snapshot light. Full URLs/summaries remain
                    # in the registry and are read via get_hotspot_detail.
                    current.append(
                        {
                            k: v
                            for k, v in brief(key, record).items()
                            if k
                            in {
                                "event_key",
                                "id",
                                "title",
                                "rank",
                                "captured_at",
                                "platform_id",
                                "feed_id",
                            }
                        }
                    )
                if entry.failed:
                    warning = "当前榜单显示上次成功数据，排名并非实时。"
            except HTTPException as error:
                warning = error.detail
        reference = None
        if payload.reference:
            ref = payload.reference
            key = f"{ref.platform_id}/{ref.feed_id}/{ref.id}"
            if key not in state["events"]:
                entry = await board(request, ref.platform_id, ref.feed_id)
                item = next(
                    (i for i in entry.snapshot.items if i["id"] == ref.id), None
                )
                if not item:
                    raise HTTPException(409, "引用热点已不在来源榜单中，请重新选择")
                # Labels are supplied by the trusted Next.js catalog, never browser titles.
                q = payload.reference_page or payload.page.model_copy(
                    update={
                        "category_id": ref.category_id,
                        "platform_id": ref.platform_id,
                        "feed_id": ref.feed_id,
                        "platform_name": ref.platform_id,
                        "board_id": None,
                        "board_name": None,
                    }
                )
                key, record = event_record(q, item, entry)
                state["events"][key] = record
            reference = brief(key, state["events"][key])
            state["active_event"] = key
        selected = next(
            (item for item in current if item["id"] == payload.selected_event_id), None
        )
        state["events"] = dict(list(state["events"].items())[-120:])
        store.save(row["id"], owner, state)
        active = state["events"].get(state.get("active_event"))
        return {
            "history": state["history"],
            "messages": state["messages"],
            "context": {
                "page": payload.page.model_dump(),
                "items": current,
                "warning": warning,
                "reference": reference,
                "selected_event": selected,
                "active_event": brief(state["active_event"], active)
                if active
                else None,
                "opinion_platforms": sorted(OPINION_PLATFORMS),
            },
        }
    except BaseException:
        store.finish(
            row["id"],
            owner,
            payload.request_id,
            row["state"]["history"],
            row["state"]["messages"],
        )
        raise


@router.post("/finish")
async def finish(payload: Finish, request: Request):
    owner, _ = owned(request, payload.thread_id)
    if len(json.dumps(payload.model_dump()).encode()) > 250000:
        raise HTTPException(413, "会话上下文过长")
    if any(
        m.get("role") not in {"user", "assistant", "toolResult"}
        for m in payload.history
    ):
        raise HTTPException(422, "无效会话角色")
    return {
        "saved": request.app.state.copilot_store.finish(
            payload.thread_id,
            owner,
            payload.request_id,
            payload.history,
            payload.messages,
        )
    }


def artifact(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "title": row["payload"]["event"]["title"],
        "message": row["message"],
        "created_at": row["created"],
    }


def result_brief(kind, body):
    if kind == "trace":
        return {
            k: body.get(k)
            for k in [
                "status",
                "subject",
                "timeline",
                "sources",
                "missing_aspects",
                "warnings",
                "suggested_queries",
            ]
        }
    return {
        "status": body["status"],
        "generated_at": body.get("generated_at"),
        "overall_assessment": body.get("overall_assessment"),
        "stats": body["stats"],
        "sections": [
            {"type": s["type"], "status": s["status"], "summary": s["summary"]}
            for s in body["sections"]
        ],
        "limitations": body.get("limitations", []),
        "sources": body.get("sources", []),
    }


def find_opinion(request, payload, owner):
    store = request.app.state.opinion_store
    with store.engine.connect() as db:
        rows = db.execute(
            select(tasks.c.id, tasks.c.payload, tasks.c.idempotency)
            .join(reports, tasks.c.id == reports.c.task_id)
            .order_by(tasks.c.updated_at.desc())
            .limit(100)
        ).mappings()
        for row in rows:
            saved = row["payload"]
            if row["idempotency"].startswith("copilot_") and not row[
                "idempotency"
            ].startswith("copilot_" + owner[:16]):
                continue
            if (
                saved["selection"]["platform_id"] == payload["selection"]["platform_id"]
                and saved["selection"]["feed_id"] == payload["selection"]["feed_id"]
                and all(
                    saved["event"].get(k) == payload["event"].get(k)
                    for k in ["id", "title", "url"]
                )
            ):
                return row["id"], store.report(row["id"])


class CopilotJobs:
    def __init__(self, state):
        self.state = state
        self.running = {}

    async def trace(self, identifier, payload):
        s = self.state
        try:
            s.copilot_store.update_job(
                identifier, status="running", message="正在执行事件溯源"
            )
            async with asyncio.timeout(s.trace_settings.task_timeout), s.trace_slots:
                result = await s.trace_graph.ainvoke(
                    {
                        "selected_event": EventTraceRequest(
                            function_id="event_tracing", **payload
                        )
                    },
                    {"recursion_limit": s.trace_settings.max_rounds * 3 + 10},
                )
            body = result["response"].model_dump(mode="json")
            s.opinion_store.cache_put(trace_cache_key(payload), body)
            s.copilot_store.update_job(
                identifier, status="completed", message="时间线已生成", result=body
            )
        except asyncio.CancelledError:
            s.copilot_store.update_job(
                identifier, status="cancelled", message="任务已取消"
            )
        except (ValueError, ProviderError) as error:
            s.copilot_store.update_job(
                identifier, status="failed", message=str(error)[:400]
            )
        except TimeoutError:
            s.copilot_store.update_job(
                identifier, status="failed", message="事件溯源超时，可重试"
            )
        except Exception:
            s.copilot_store.update_job(
                identifier, status="failed", message="事件溯源服务失败，请检查配置"
            )
        finally:
            self.running.pop(identifier, None)

    async def close(self):
        running = list(self.running.values())
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)


@router.post("/tools")
async def tools(call: ToolCall, request: Request):
    owner, row = owned(request, call.thread_id)
    s = request.app.state
    state = row["state"]
    args = call.args
    name = call.name
    if (
        row["lease"] != call.request_id
        or row["lease_until"] < __import__("time").time()
    ):
        raise HTTPException(409, "工具只能在当前有效会话回答期间执行")
    sources = []
    if name == "search_hotspots":
        if not args.query:
            raise HTTPException(422, "需要搜索词")
        found = []
        if args.platform_id and args.feed_id:
            await board(request, args.platform_id, args.feed_id)
        for key, entry in s.board_service.boards.items():
            platform, feed = key.split("/", 1)
            if (
                not entry.snapshot
                or (args.platform_id and platform != args.platform_id)
                or (args.feed_id and feed != args.feed_id)
            ):
                continue
            definition = state.get("catalog", {}).get(key)
            if not definition:
                continue
            q = Query.model_validate(definition)
            for item in entry.snapshot.items:
                if args.query.casefold() not in item["title"].casefold():
                    continue
                k, record = event_record(q, item, entry)
                state["events"][k] = record
                found.append(brief(k, record))
                if len(found) >= 10:
                    break
            if len(found) >= 10:
                break
        s.copilot_store.save(row["id"], owner, state)
        return {
            "data": {
                "items": found,
                "coverage": "仅当前已缓存、已接入的真实榜单，不代表全网覆盖",
            }
        }
    if name in {"web_search", "fetch_webpage"}:
        try:
            if name == "web_search":
                if not args.query:
                    raise HTTPException(422, "需要搜索词")
                hits = await s.copilot_clients.search(args.query)
                data = [h.model_dump() for h in hits[:5]]
                sources = [{"title": h.title, "url": h.url} for h in hits[:5]]
            else:
                if not args.url:
                    raise HTTPException(422, "需要网页链接")
                page = await s.copilot_clients.fetch(public_url(args.url))
                data = page.model_dump()
                data["content"] = data["content"][:12000]
                sources = [{"title": page.title, "url": args.url}]
        except (ProviderError, UnsafeURL) as error:
            raise HTTPException(502, str(error)) from None
        return {"data": data, "sources": sources}
    record = state["events"].get(args.event_key)
    if not record:
        raise HTTPException(422, "热点标识未被服务端核验，请先查找真实热点")
    state["active_event"] = args.event_key
    s.copilot_store.save(row["id"], owner, state)
    if name == "get_hotspot_detail":
        return {
            "data": record,
            "sources": [
                {"title": record["event"]["title"], "url": record["event"]["url"]}
            ]
            if record["event"]["url"]
            else [],
        }
    kind = "opinion" if "opinion" in name else "trace"
    if (
        kind == "opinion"
        and record["selection"]["platform_id"] not in OPINION_PLATFORMS
    ):
        raise HTTPException(
            422,
            "Copilot 舆情分析仅支持微博、小红书、百度贴吧；不能提供该平台的评论统计。",
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                kind,
                record["selection"]["platform_id"],
                record["selection"]["feed_id"],
                {k: record["event"].get(k) for k in ["id", "title", "url"]},
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    job = s.copilot_store.recent(fingerprint, owner)
    if not job or args.refresh:
        cached = (
            s.opinion_store.cache_get(trace_cache_key(record))
            if kind == "trace"
            else None
        )
        saved = find_opinion(request, record, owner) if kind == "opinion" else None
        if name.startswith("get_") and not (cached or saved):
            return {"data": {"found": False, "message": "暂无该热点已保存的分析结果"}}
        if name.startswith("get_") or not args.refresh:
            if cached or saved:
                job = s.copilot_store.new_job(owner, fingerprint, kind, record)
                values = {
                    "status": "completed",
                    "message": "复用已有分析结果",
                    "result": cached if kind == "trace" else saved[1],
                }
                if saved:
                    values["task_id"] = saved[0]
                s.copilot_store.update_job(job["id"], **values)
                job = {**job, **values}
        if not job or args.refresh:
            # Recheck event against today's server snapshot before starting paid work.
            verified = canonical_event(
                EventTraceRequest(function_id="event_tracing", **record),
                s.board_service,
            )
            payload = {
                "selection": verified.selection.model_dump(mode="json"),
                "event": verified.event.model_dump(mode="json"),
            }
            if kind == "trace" and len(s.copilot_jobs.running) >= 4:
                raise HTTPException(429, "事件分析队列已满")
            task = None
            if kind == "opinion":
                req = OpinionRequest(
                    function_id="public_opinion",
                    idempotency_key="copilot_"
                    + owner[:16]
                    + fingerprint[:32]
                    + (uuid4().hex[:8] if args.refresh else ""),
                    **payload,
                )
                task = await create_task(req, request)
            job = s.copilot_store.new_job(owner, fingerprint, kind, payload)
            if task:
                s.copilot_store.update_job(job["id"], task_id=task["id"])
                job["task_id"] = task["id"]
            else:
                s.copilot_jobs.running[job["id"]] = asyncio.create_task(
                    s.copilot_jobs.trace(job["id"], payload)
                )
    if job["id"] not in state["artifacts"]:
        state["artifacts"].append(job["id"])
    s.copilot_store.save(row["id"], owner, state)
    result = await read_result(job["id"], call.thread_id, request)
    data = {
        "artifact": result["artifact"],
        "analysis": result_brief(kind, result["result"])
        if result.get("result")
        else None,
        "note": "未完成任务不能描述为分析成功；停止聊天不会自动取消后台任务。",
    }
    return {"data": data, "artifact": result["artifact"]}


@router.get("/results/{identifier}")
async def read_result(identifier: str, thread_id: str, request: Request):
    owner, row = owned(request, thread_id)
    s = request.app.state
    if identifier not in row["state"]["artifacts"]:
        raise HTTPException(404, "该会话无权读取此结果")
    job = s.copilot_store.job(identifier, owner)
    if not job:
        raise HTTPException(404, "分析结果不存在")
    result = job["result"]
    task = None
    if job["kind"] == "opinion" and not result and job["task_id"]:
        task = s.opinion_store.get_task(job["task_id"])
        if task:
            job.update(status=task["status"], message=task["message"])
            result = s.opinion_store.report(job["task_id"])
    return {
        "artifact": artifact(job),
        "result": result,
        "progress": s.opinion_store.task_events(job["task_id"]) if task else [],
    }


@router.delete("/results/{identifier}")
async def cancel_result(identifier: str, thread_id: str, request: Request):
    current = await read_result(identifier, thread_id, request)
    owner, _ = owned(request, thread_id)
    s = request.app.state
    job = s.copilot_store.job(identifier, owner)
    if current["result"] or current["artifact"]["status"] not in {"running", "queued"}:
        raise HTTPException(409, "该分析已结束，无需取消")
    if job["kind"] == "opinion":
        task = s.opinion_store.get_task(job["task_id"])
        if not task or not task["idempotency"].startswith("copilot_" + owner[:16]):
            raise HTTPException(409, "复用的实验室任务请从实验室管理")
        await s.opinion_tasks.cancel(job["task_id"])
    else:
        running = s.copilot_jobs.running.get(identifier)
        if running:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
    return {"cancelled": True}
