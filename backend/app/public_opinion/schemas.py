from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator

from ..event_trace.schemas import EventSelection, Identifier, Schema, SelectedHotEvent

SortMode = Literal["hot", "score", "time", "unknown"]
SectionType = Literal["discussion_topics", "public_emotions", "opinion_clusters", "stance_analysis",
                      "controversies", "trends", "representative_comments", "contextual_insights"]


class OpinionRequest(Schema):
    function_id: Literal["public_opinion"]
    selection: EventSelection
    event: SelectedHotEvent
    dataset_id: Identifier | None = None
    idempotency_key: Identifier


class Post(Schema):
    id: str = Field(min_length=1, max_length=120)
    platform_id: str
    url: str = Field(max_length=8192)
    title: str = Field(default="", max_length=1000)
    summary: str = Field(default="", max_length=2000)
    published_at: datetime | None = None
    relevance: str = Field(default="", max_length=1000)
    verification: Literal["page_read", "authorized_import"]
    read_method: Literal["public_fetch", "authorized_platform"] | None = None


class CommentInput(Schema):
    platform_id: str
    post_id: str = Field(min_length=1, max_length=120)
    comment_id: str = Field(min_length=1, max_length=120)
    source_rank: int | None = Field(default=None, ge=1)
    sort_mode: SortMode = "unknown"
    content: str = Field(max_length=30000)
    created_at: datetime | None = None
    like_count: int | None = Field(default=None, ge=0)
    parent_comment_id: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=8192)
    collected_at: datetime | None = None

    @field_validator("created_at", "collected_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("评论时间须包含时区，未知时间请留空")
        return value


class Comment(CommentInput):
    raw_content: str
    duplicate_text: bool = False


class ImportRequest(Schema):
    selection: EventSelection
    event: SelectedHotEvent
    format: Literal["json", "csv"]
    content: str = Field(min_length=1, max_length=4_000_000)
    authorized: Literal[True]


class Evidence(Schema):
    post_id: str
    comment_id: str


class Group(Schema):
    label: str = Field(min_length=1, max_length=100)
    explanation: str = Field(default="", max_length=1600)
    evidence: list[Evidence] = Field(default_factory=list, max_length=1000)
    # Never provided by a model: calculated after validating comment assignments.
    count: int = 0
    percent: float | None = None


class ExternalSource(Schema):
    id: str
    title: str
    url: str
    published_at: str | None = None
    access: Literal["summary", "body"] = "summary"


class ContextQuote(Schema):
    source_id: str
    excerpt: str = Field(min_length=8, max_length=500)


class ContextInsight(Schema):
    title: str = Field(max_length=200)
    dimension: Literal["temporal", "spatial", "historical", "cultural", "communication", "coverage"]
    explanation: str = Field(max_length=2000)
    classification: Literal["verified_fact", "supported_inference", "unverified_hypothesis", "insufficient_evidence"]
    source_ids: list[str] = Field(max_length=10)
    evidence: list[ContextQuote] = Field(default_factory=list, max_length=8)
    time_range: str | None = Field(default=None, max_length=150)
    uncertainty: str = Field(max_length=800)


class Section(Schema):
    type: SectionType
    title: str = Field(max_length=120)
    status: Literal["completed", "not_applicable", "insufficient_data", "failed"]
    summary: str = Field(max_length=2000)
    data: list[Group] = Field(default_factory=list, max_length=40)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
    contextual_insights: list[ContextInsight] = Field(default_factory=list, max_length=8)
    sample_size: int | None = None
    analyzed_sample: list[Evidence] = Field(default_factory=list, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)
    issue: str | None = Field(default=None, max_length=300)


class ChartPoint(Schema):
    id: str
    label: str
    count: int = Field(ge=0)
    percent: float | None = Field(default=None, ge=0, le=100)
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    start_at: str | None = None
    end_at: str | None = None
    metric_definition: str | None = None


class OpinionChart(Schema):
    id: str
    type: Literal["emotion_distribution", "discussion_topics", "stance_comparison", "comment_timeline", "post_contribution", "discussion_radar"]
    title: str
    description: str
    sample_size: int = Field(ge=1)
    unit: Literal["条", "%"] = "条"
    points: list[ChartPoint]
    overlapping: bool = False
    issue: str | None = None
    timezone: str | None = None
    granularity: str | None = None
    normalization: Literal["comment_share"] | None = None

    @model_validator(mode="after")
    def defined_radar_metrics(self):
        if self.type == "discussion_radar":
            if self.unit != "%" or self.normalization != "comment_share" or len(self.points) < 3:
                raise ValueError("雷达图须至少三个指标，使用同一评论样本占比量纲")
            if len({point.id for point in self.points}) != len(self.points):
                raise ValueError("雷达指标不能重复")
            for point in self.points:
                refs = {(ref.post_id, ref.comment_id) for ref in point.evidence}
                if (not point.metric_definition or point.percent is None or point.count > self.sample_size
                        or len(refs) != point.count or abs(point.percent - round(point.count / self.sample_size * 100, 1)) > .01):
                    raise ValueError("雷达指标须有定义、真实评论引用及按共同分母计算的占比")
        return self


class ContextNode(Schema):
    id: str
    kind: Literal["capture", "post", "source", "insight"]
    title: str
    description: str
    occurred_at: str | None = None
    time_label: str
    classification: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    post_id: str | None = None
    evidence: list[ContextQuote] = Field(default_factory=list)
    uncertainty: str = ""


class DatasetStats(Schema):
    post_count: int
    contributing_post_count: int = 0
    collected_count: int
    analyzed_count: int
    prepared_count: int = 0
    input_count: int = 0
    origin: Literal["imported", "collected"] = "collected"
    reply_count: int
    per_post: dict[str, int]
    sort_modes: list[SortMode]
    time_start: str | None = None
    time_end: str | None = None
    limitations: list[str]


class OverallAssessment(Schema):
    summary: str = Field(default="", max_length=1400)
    core_judgment: str | None = Field(default=None, max_length=250)
    key_findings: list[str] = Field(default_factory=list, max_length=4)
    section_types: list[SectionType] = Field(default_factory=list, max_length=8)
    evidence: list[Evidence] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    status: Literal["completed", "partial", "legacy", "unavailable"] = "completed"
    reason: str | None = Field(default=None, max_length=600)


class ChartInterpretation(Schema):
    chart_id: str
    analysis: str = Field(min_length=1, max_length=800)
    evidence: list[Evidence] = Field(default_factory=list, max_length=6)
    source_ids: list[str] = Field(default_factory=list, max_length=6)


class ReportSynthesis(Schema):
    overall_assessment: OverallAssessment
    chart_interpretations: list[ChartInterpretation] = Field(default_factory=list, max_length=8)


class ResearchOutput(Schema):
    section_types: list[SectionType] = Field(max_length=8)
    contextual_insights: list[ContextInsight] = Field(default_factory=list, max_length=8)


class DiscoveryChoice(Schema):
    post_ids: list[str] = Field(max_length=20)
    limitations: list[str] = Field(max_length=10)


class OpinionReport(Schema):
    task_id: str
    dataset_id: str
    selection: EventSelection
    selected_event: SelectedHotEvent
    generated_at: str
    status: Literal["completed", "partial"]
    overall_assessment: OverallAssessment = Field(validation_alias=AliasChoices("overall_assessment", "insight"))
    chart_interpretations: list[ChartInterpretation] = Field(default_factory=list)
    stats: DatasetStats
    sections: list[Section]
    posts: list[Post]
    sources: list[ExternalSource]
    limitations: list[str]
    usage: dict[str, int]
    charts: list[OpinionChart] = Field(default_factory=list)
    context_timeline: list[ContextNode] = Field(default_factory=list)
    visualization_notes: dict[str, str] = Field(default_factory=dict)

    @field_validator("overall_assessment", mode="before")
    @classmethod
    def migrate_legacy_assessment(cls, value):
        if isinstance(value, str):
            boilerplate = {"本次仅完成部分评论研究，请结合以下模块和数据范围理解结果。",
                           "本次研究聚焦有限前排评论中的讨论，请结合以下有评论依据的分析模块及程序统计理解结果。"}
            if value.strip() in boilerplate:
                return {"status": "unavailable", "reason": "此历史任务没有生成完整的综合评价；保留已完成的分析与证据，未自动补写结论。"}
            return {"summary": value[:1400], "status": "legacy", "reason": "保留历史任务实际生成的摘要，未重新调用模型扩写。"}
        return value
