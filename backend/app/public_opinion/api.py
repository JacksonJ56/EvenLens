from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError

from ..event_trace.api import canonical_event
from ..event_trace.schemas import EventTraceRequest
from .preparation import parse_import, prepare_comments
from .collector import MediaCrawlerAdapter
from .schemas import ImportRequest, OpinionRequest, OpinionReport
from .visualization import enrich_report, identity
from .settings import PLATFORMS
from .store import binding

router = APIRouter(prefix="/api/public-opinion", tags=["public-opinion"])


def supported(platform):
    if platform not in PLATFORMS:
        raise HTTPException(422, "当前平台暂不支持公众舆情分析，请重新选择支持的平台。")


def canonical(payload, state):
    supported(payload.selection.platform_id)
    verified = canonical_event(EventTraceRequest(function_id="event_tracing", selection=payload.selection, event=payload.event),
                               state.board_service)
    return payload.model_copy(update={"event": verified.event})


@router.get("/capabilities")
async def capabilities(request: Request):
    state = request.app.state
    sessions = getattr(state, "opinion_sessions", None)
    return {"platforms": {platform: {"supported": True, "adapter": code, "adapter_implemented": True,
            "session_verified": bool(sessions and sessions.status(platform)["session_verified"]), "runtime_check": "before_task_creation",
            "collector_ready": bool(sessions and sessions.status(platform)["collector_ready"]),
            "collector_configured": (status := state.opinion_settings.collector_status(platform))[0], "message": status[1]}
            for platform, code in PLATFORMS.items()},
            "import_available": True, "llm_configured": bool(state.trace_settings.llm_key and state.trace_settings.llm_model)}


@router.post("/datasets/import", status_code=201)
async def import_comments(request: Request):
    # Bound request bodies before JSON parsing; file bytes stay local to the backend.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 5_000_000:
            raise HTTPException(413, "评论文件过大，请控制在 4 MB 内")
    try:
        payload = ImportRequest.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "导入参数无效：须包含热点上下文、授权声明和 JSON/CSV 内容") from None
    state = request.app.state
    payload = canonical(payload, state)
    try:
        posts, rows = parse_import(payload.content, payload.format, payload.selection.platform_id)
        prepared, stats = prepare_comments(posts, rows, state.opinion_settings)
    except (ValueError, ValidationError, TypeError, KeyError):
        raise HTTPException(422, "评论文件字段、日期、帖子链接或平台不匹配，请参照导入格式说明") from None
    if not stats.prepared_count:
        raise HTTPException(422, "文件没有可分析的有效一级评论")
    dataset_id = state.opinion_store.save_dataset(payload, posts[:state.opinion_settings.max_posts], prepared, stats)
    return {"dataset_id": dataset_id, "stats": stats.model_dump(), "binding": binding(payload)}


@router.post("/tasks", status_code=202)
async def create_task(payload: OpinionRequest, request: Request):
    state = request.app.state
    payload = canonical(payload, state)
    if not state.trace_settings.llm_key or not state.trace_settings.llm_model:
        raise HTTPException(503, "未配置舆情模型；复用 EVENT_TRACE_LLM_API_KEY / EVENT_TRACE_LLM_MODEL")
    if payload.dataset_id:
        dataset = state.opinion_store.dataset(payload.dataset_id)
        if not dataset or dataset["binding"] != binding(payload):
            raise HTTPException(409, "导入数据不属于当前热点、平台或榜单，请重新导入")
    else:
        ready, reason = state.opinion_settings.collector_status(payload.selection.platform_id)
        if not ready:
            raise HTTPException(503, reason)
        if not state.trace_settings.search_key:
            raise HTTPException(503, "未配置 DeepSeek Search；可以改用合法评论文件导入")
        sessions = getattr(state, "opinion_sessions", None)
        if sessions is None:
            raise HTTPException(503, "平台会话服务未初始化，请重启后端")
        await sessions.require_verified(payload.selection.platform_id)
        try:
            await MediaCrawlerAdapter(state.opinion_settings).preflight()
        except (ValueError, OSError) as error:
            raise HTTPException(503, str(error) if isinstance(error, ValueError) else "无法启动 MediaCrawler 独立解释器") from None
    task, created = state.opinion_store.create_task(payload)
    if not created and (task["payload"]["selection"] != payload.selection.model_dump() or
                        task["payload"]["event"]["id"] != payload.event.id or task["payload"].get("dataset_id") != payload.dataset_id):
        raise HTTPException(409, "幂等键已用于其他任务")
    if created:
        try:
            state.opinion_tasks.start(task["id"])
        except ValueError as error:
            state.opinion_store.update_task(task["id"], status="failed", message=str(error))
            raise HTTPException(429, str(error)) from None
    return public_task(task)


def public_task(task):
    return {k: task[k] for k in ["id", "status", "stage", "message", "created_at", "updated_at", "usage"]} | {"history": task.get("history", [])}


def find_task(request, task_id):
    task = request.app.state.opinion_store.get_task(task_id)
    if not task:
        raise HTTPException(404, "舆情任务不存在")
    return task | {"history": request.app.state.opinion_store.task_events(task_id)}


@router.get("/tasks/{task_id}")
async def task_status(task_id: str, request: Request):
    return public_task(find_task(request, task_id))


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str, request: Request):
    task = find_task(request, task_id)
    if task["status"] in {"queued", "running", "interrupted", "failed"}:
        await request.app.state.opinion_tasks.cancel(task_id)
    return public_task(find_task(request, task_id))


@router.post("/tasks/{task_id}/resume", status_code=202)
async def resume_task(task_id: str, request: Request):
    task = find_task(request, task_id)
    if task["status"] not in {"failed", "cancelled", "interrupted"}:
        raise HTTPException(409, "仅失败、取消或中断的任务可以恢复")
    if not task["checkpoint"].get("collection_done") and not task["payload"].get("dataset_id"):
        await request.app.state.opinion_sessions.require_verified(task["payload"]["selection"]["platform_id"])
    # Reuse the immutable canonical selection snapshot; never attach a new browser selection.
    request.app.state.opinion_store.update_task(task_id, status="queued", message="正在恢复任务")
    try:
        request.app.state.opinion_tasks.start(task_id)
    except ValueError as error:
        request.app.state.opinion_store.update_task(task_id, status="failed", message=str(error))
        raise HTTPException(429, str(error)) from None
    return public_task(find_task(request, task_id))


@router.get("/tasks/{task_id}/report")
async def task_report(task_id: str, request: Request):
    task = find_task(request, task_id)
    report = request.app.state.opinion_store.report(task_id)
    if task["status"] not in {"completed", "partial"} or not report:
        raise HTTPException(409, "报告尚未生成")
    # Project legacy reports too, without running the Agent or modifying saved data.
    return enrich_report(OpinionReport.model_validate(report),
        request.app.state.opinion_store.read_comments(report["dataset_id"]))


@router.get("/tasks/{task_id}/chart-comments")
async def chart_comments(task_id: str, request: Request, chart_id: str, point_id: str,
                         offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=30), preview: bool = False):
    report = await task_report(task_id, request)
    chart = next((chart for chart in report.charts if chart.id == chart_id), None)
    point = next((point for point in chart.points if point.id == point_id), None) if chart else None
    if point is None:
        raise HTTPException(404, "图表或数据项不存在")
    keys = {identity(ref) for ref in point.evidence}
    rows = [row for row in request.app.state.opinion_store.read_comments(report.dataset_id)
            if (row["post_id"], row["comment_id"]) in keys and not row.get("parent_comment_id")]
    page = rows[offset:offset + limit]
    return {"comments": [comment_preview(row) for row in page] if preview else page,
            "total": len(rows), "offset": offset, "limit": limit}


def comment_preview(row):
    value = {key: val for key, val in row.items() if key != "raw_content"}
    value.update(content=row["content"][:240], is_preview=True)
    return value


@router.get("/tasks/{task_id}/evidence")
async def evidence_page(task_id: str, request: Request, section_index: int | None = Query(None, ge=0),
                        group_index: int | None = Query(None, ge=0), assessment: bool = False,
                        chart_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(3, ge=1, le=20)):
    report = await task_report(task_id, request)
    if sum([section_index is not None, assessment, chart_id is not None]) != 1:
        raise HTTPException(422, "请指定一组报告证据")
    if group_index is not None and section_index is None:
        raise HTTPException(422, "分组必须属于指定分析模块")
    refs = []
    if assessment:
        refs = report.overall_assessment.evidence
    elif chart_id is not None:
        chart = next((chart for chart in report.charts if chart.id == chart_id), None)
        if chart is None:
            raise HTTPException(404, "图表不存在")
        interpretation = next((item for item in report.chart_interpretations if item.chart_id == chart_id), None)
        all_refs = [ref for point in chart.points for ref in point.evidence]
        chart_keys = {identity(ref) for ref in all_refs}
        refs = [ref for ref in interpretation.evidence if identity(ref) in chart_keys] if interpretation and interpretation.evidence else all_refs
    else:
        if section_index >= len(report.sections):
            raise HTTPException(404, "分析模块不存在")
        section = report.sections[section_index]
        if group_index is not None:
            if group_index >= len(section.data):
                raise HTTPException(404, "分析分组不存在")
            refs = section.data[group_index].evidence
        else:
            refs = section.evidence
    allowed = {identity(ref) for ref in refs}
    rows = [row for row in request.app.state.opinion_store.read_comments(report.dataset_id)
            if (row["post_id"], row["comment_id"]) in allowed]
    return {"comments": [comment_preview(row) for row in rows[offset:offset + limit]],
            "total": len(rows), "offset": offset, "limit": limit}


@router.get("/tasks/{task_id}/comments")
async def report_comments(task_id: str, request: Request, post_id: str, comment_id: str):
    task = find_task(request, task_id)
    dataset_id = task["checkpoint"].get("dataset_id") or task["payload"].get("dataset_id")
    if not dataset_id:
        raise HTTPException(409, "评论数据尚未保存")
    rows = request.app.state.opinion_store.read_comments(dataset_id, post_id=post_id, ids=[comment_id], limit=1)
    if not rows:
        raise HTTPException(404, "引用的评论不存在")
    return rows[0]


@router.get("/tasks/{task_id}/sources/{source_id}")
async def source_snapshot(task_id: str, source_id: str, request: Request):
    find_task(request, task_id)
    source = request.app.state.opinion_store.source(task_id, source_id)
    if not source:
        raise HTTPException(404, "来源快照不存在")
    return source
