"""Deterministic projections of saved comment assignments, never model-provided scores.

Also applied to legacy reports at read time; no new LLM requests or schema migration.
All drill-down filters are the exact (post_id, comment_id) sets used for counts.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .analysis import EMOTIONS
from .schemas import ChartPoint, ContextNode, Evidence, OpinionChart, OpinionReport
from .discussion_metrics import discussion_metrics

SCOPE = "本次保留的有效一级评论样本，不代表全平台公众。"


def identity(value):
    return value.post_id, value.comment_id


def timestamp(value):
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except (ValueError, TypeError):
        return None


def references(keys, roots):
    return [Evidence(post_id=p, comment_id=c) for p, c in roots if (p, c) in keys]


def group_chart(section, index, roots):
    if section.status not in {"completed", "insufficient_data"} or not section.analyzed_sample:
        return None
    sample = {identity(ref) for ref in section.analyzed_sample} & roots.keys()
    if not sample:
        return None
    kind = {"public_emotions": "emotion_distribution", "discussion_topics": "discussion_topics",
            "stance_analysis": "stance_comparison"}.get(section.type)
    if not kind or kind == "stance_comparison" and not (section.issue or "").strip():
        return None
    buckets, descriptions, assigned = {}, {}, set()
    for group in section.data:
        keys = {identity(ref) for ref in group.evidence} & sample
        if kind != "discussion_topics":
            keys -= assigned
        label = group.label
        if kind == "emotion_distribution" and label not in EMOTIONS:
            label = "无法判断"
        buckets.setdefault(label, set()).update(keys)
        descriptions.setdefault(label, group.explanation)
        assigned |= keys
    if kind == "stance_comparison" and not assigned:
        return None
    if kind in {"emotion_distribution", "stance_comparison"} and sample - assigned:
        label = "无法判断" if kind == "emotion_distribution" else "未分类"
        buckets.setdefault(label, set()).update(sample - assigned)
        descriptions[label] = "已完成批次中未获得可靠分类的评论，仍保留在统计分母中。"
    points = [ChartPoint(id=f"group-{i}", label=label, count=len(keys),
                 percent=round(len(keys) / len(sample) * 100, 1), explanation=descriptions[label],
                 evidence=references(keys, roots)) for i, (label, keys) in enumerate(buckets.items()) if keys]
    points.sort(key=lambda point: -point.count)
    if not points:
        return None
    overlap = len(set.union(*buckets.values())) < sum(len(keys) for keys in buckets.values())
    description = SCOPE
    if kind == "discussion_topics":
        description += " 同一评论可属于多个主题，主题占比不相加为 100%；未归属评论仍计入样本量。"
    else:
        description += " 每条评论仅计入一个类别；无法判断/未分类保留在分母中。"
    if section.status == "insufficient_data":
        description += " 此模块仅完成部分批次。"
    return OpinionChart(id=f"section-{index}", type=kind, title=section.title, sample_size=len(sample),
                        points=points, description=description, overlapping=overlap, issue=section.issue)


def time_chart(roots):
    dated = [(timestamp(row.get("created_at")), key) for key, row in roots.items()]
    dated = [(date, key) for date, key in dated if date is not None]
    if len(dated) < 6 or len(dated) / len(roots) < .8:
        return None
    span = max(d for d, _ in dated) - min(d for d, _ in dated)
    minutes, grain = (15, "15 分钟") if span < timedelta(hours=6) else (60, "小时") if span <= timedelta(days=2) else (1440, "天") if span <= timedelta(days=60) else (10080, "周")
    zone = ZoneInfo("Asia/Shanghai")
    groups = defaultdict(set)
    for date, key in dated:
        local = date.astimezone(zone)
        if minutes <= 60:
            start = local.replace(minute=(local.minute // minutes) * minutes, second=0, microsecond=0)
        else:
            start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            if minutes == 10080:
                start -= timedelta(days=start.weekday())
        groups[start].add(key)
    if len(groups) < 3:
        return None
    points = [ChartPoint(id=f"time-{i}", label=start.strftime("%m/%d %H:%M" if minutes <= 60 else "%Y/%m/%d"),
              start_at=start.isoformat(), end_at=(start + timedelta(minutes=minutes)).isoformat(), count=len(keys),
              evidence=references(keys, roots), explanation="该时间段实际保存的一级评论；不代表该时间段的全量评论。")
              for i, (start, keys) in enumerate(sorted(groups.items()))]
    return OpinionChart(id="comment-time", type="comment_timeline", title="已采集样本的评论发布时间分布",
        description=f"{SCOPE}按{grain}聚合，仅绘制存在真实记录的时间段，不填补缺失时段。有效时间 {len(dated)}/{len(roots)} 条；时区 Asia/Shanghai。",
        sample_size=len(dated), points=points, timezone="Asia/Shanghai", granularity=grain)


def context_nodes(report):
    insights = [insight for section in report.sections if section.status in {"completed", "insufficient_data"}
                for insight in section.contextual_insights]
    if not insights:
        return []
    sources = {source.id: source for source in report.sources}
    insights = [i for i in insights if i.source_ids and all(sid in sources and sources[sid].access == "body" for sid in i.source_ids)
                and {quote.source_id for quote in i.evidence} == set(i.source_ids)]
    if not insights:
        return []
    nodes = [ContextNode(id="event-capture", kind="capture", title=report.selected_event.title,
        description="热点记录的抓取时刻，不能当作事件实际发生时间。", occurred_at=report.selected_event.captured_at.isoformat() if report.selected_event.captured_at else None,
        time_label="热点抓取时间（非事件发生时间）")]
    for i, post in enumerate(report.posts):
        if post.published_at:
            nodes.append(ContextNode(id=f"post-{i}", kind="post", title=post.title or post.id,
                occurred_at=post.published_at.isoformat(), time_label="相关帖子发布时间（非事件发生时间）",
                description="此时间来自已获取帖子记录，不能直接认定为热点事件的起点。", post_id=post.id))
    for sid in dict.fromkeys(sid for i in insights for sid in i.source_ids):
        source = sources[sid]
        # Keep date-only publication precision, never infer an insight's event time.
        date = timestamp(source.published_at)
        try:
            day = datetime.strptime(source.published_at or "", "%Y-%m-%d").date().isoformat()
        except ValueError:
            day = None
        nodes.append(ContextNode(id=f"source-{sid}", kind="source", title=source.title,
            description="关联背景资料的发布时间，不能自动视为事件发生时间。",
            occurred_at=date.isoformat() if date else day, time_label="资料发布时间" if date or day else "资料发布时间未知", source_ids=[sid]))
    for i, insight in enumerate(insights):
        nodes.append(ContextNode(id=f"insight-{i}", kind="insight", title=insight.title,
            description=insight.explanation, time_label=insight.time_range or "关联时间未确定", classification=insight.classification,
            source_ids=insight.source_ids, evidence=insight.evidence, uncertainty=insight.uncertainty))
    def order(node):
        date = timestamp(node.occurred_at)
        if date is None and node.occurred_at:
            date = datetime.fromisoformat(node.occurred_at).replace(tzinfo=timezone.utc)
        return date or datetime.max.replace(tzinfo=timezone.utc)
    return sorted(nodes, key=order)


def enrich_report(report: OpinionReport, comments: list[dict]) -> OpinionReport:
    roots = {(c["post_id"], c["comment_id"]): c for c in comments if not c.get("parent_comment_id")}
    charts = [chart for i, section in enumerate(report.sections) if (chart := group_chart(section, i, roots))]
    notes = {}
    if chart := discussion_metrics(report, roots):
        charts.append(chart)
    else:
        notes["radar"] = "样本特征图需要至少 20 条已完成分析的一级评论、三个有明确定义和共同分母的指标，且存在非零观测；当前不满足，不生成评分。"
    if roots:
        post_points = []
        for i, post in enumerate(report.posts):
            keys = {key for key in roots if key[0] == post.id}
            post_points.append(ChartPoint(id=f"post-{i}", label=post.title or post.id, count=len(keys),
                percent=round(len(keys) / len(roots) * 100, 1), evidence=references(keys, roots), explanation=f"帖子 ID：{post.id}；保留的有效一级评论。"))
        if any(p.count for p in post_points):
            charts.append(OpinionChart(id="post-contribution", type="post_contribution", title="帖子评论贡献",
                sample_size=len(roots), points=sorted(post_points, key=lambda p: -p.count), description=SCOPE + "展示实际保留量，包含尚未完成语义分析的评论；不能解释为帖子总热度。"))
        if chart := time_chart(roots):
            charts.append(chart)
        else:
            notes["comment_timeline"] = "评论时间记录不足：至少 6 条带时区的有效时间、覆盖率 80% 且分布于 3 个聚合时段时才展示。"
    if not any(c.type == "stance_comparison" for c in charts):
        notes["stance_comparison"] = "没有已保存的明确议题与有效立场分类，不展示支持/反对图。"
    if not any(c.type == "emotion_distribution" for c in charts):
        notes["emotion_distribution"] = "本次没有完成可核验的情绪分类，暂不绘制情绪图；不能从主题或点赞数推测情绪。"
    if not any(c.type == "discussion_topics" for c in charts):
        notes["discussion_topics"] = "本次尚无带有效评论归属的主题分析，不绘制主题数量。"
    stats = report.stats.model_copy(update={"contributing_post_count": len({key[0] for key in roots})})
    return report.model_copy(update={"stats": stats, "charts": charts, "context_timeline": context_nodes(report), "visualization_notes": notes})
