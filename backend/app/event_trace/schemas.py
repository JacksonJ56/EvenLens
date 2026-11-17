from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
TimePrecision = Literal["datetime", "date", "month", "year", "unknown"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventSelection(Schema):
    category_id: Identifier
    category_name: Label
    platform_id: Identifier
    platform_name: Label
    # feed_id identifies the underlying feed even when there is no secondary selector.
    feed_id: Identifier
    board_id: Identifier | None = None
    board_name: Label | None = None


class SelectedHotEvent(Schema):
    id: Identifier
    title: Title
    url: str | None = Field(default=None, max_length=8192)
    summary: str | None = Field(default=None, max_length=2000)
    rank: int | None = Field(default=None, ge=1)
    captured_at: datetime | None = None


class EventTraceRequest(Schema):
    function_id: Literal["event_tracing"]
    selection: EventSelection
    event: SelectedHotEvent


class SearchPlan(Schema):
    subject: Title
    ambiguous: bool
    queries: list[Query] = Field(min_length=1, max_length=6)
    priorities: list[Label] = Field(default_factory=list, max_length=8)


class Evaluation(Schema):
    subject: Title | None
    resolved: bool
    sufficient: bool
    missing_aspects: list[Title] = Field(max_length=12)
    next_queries: list[Query] = Field(max_length=6)
    reason: Title


class EvidenceProposal(Schema):
    source_id: Identifier
    kind: Literal["body", "snippet", "summary"]
    excerpt: str = Field(min_length=8, max_length=360)


class EventProposal(Schema):
    title: Title
    description: str = Field(min_length=1, max_length=2000)
    occurred_at: str | None = Field(max_length=48)
    time_precision: TimePrecision
    evidence: list[EvidenceProposal] = Field(min_length=1, max_length=10)
    uncertainty: str | None = Field(default=None, max_length=600)


class Extraction(Schema):
    events: list[EventProposal] = Field(max_length=16)
    missing_aspects: list[Title] = Field(default_factory=list, max_length=12)


class Evidence(EvidenceProposal):
    # Offset in the whitespace-normalized evidence text, not an offset into HTML.
    offset: int = Field(ge=0)


class EvidenceSource(Schema):
    id: Identifier
    title: str
    url: str
    published_at: str | None = None
    site_name: str | None = None
    access: Literal["body", "summary", "unavailable"]
    fetch_status: Literal["not_attempted", "fetched", "failed", "blocked"]
    fetch_error: str | None = None


class TimelineEvent(Schema):
    id: Identifier
    title: str
    description: str
    occurred_at: str | None
    time_precision: TimePrecision
    source_ids: list[Identifier]
    evidence: list[Evidence]
    uncertainty: str | None = None


class EventTraceResponse(Schema):
    trace_id: Identifier
    selection: EventSelection
    selected_event: SelectedHotEvent
    subject: str | None
    status: Literal["completed", "partial"]
    search_rounds: int
    search_queries: list[list[str]]
    suggested_queries: list[str]
    timeline: list[TimelineEvent]
    sources: list[EvidenceSource]
    missing_aspects: list[str]
    warnings: list[str]
