export interface TraceSelection {
  category_id: string;
  category_name: string;
  platform_id: string;
  platform_name: string;
  feed_id: string;
  board_id: string | null;
  board_name: string | null;
}

export interface TraceHotEvent {
  id: string;
  title: string;
  url: string | null;
  summary: string | null;
  rank: number | null;
  captured_at: string | null;
}

export interface TraceRequest {
  function_id: "event_tracing";
  selection: TraceSelection;
  event: TraceHotEvent;
}

export interface TraceEvidence {
  source_id: string;
  kind: "body" | "snippet" | "summary";
  excerpt: string;
  offset: number;
}

export interface TraceSource {
  id: string;
  url: string;
  title: string;
  site_name: string | null;
  published_at: string | null;
  access: "body" | "summary" | "unavailable";
  fetch_status: "not_attempted" | "fetched" | "failed" | "blocked";
  fetch_error: string | null;
}

export interface TraceTimelineEvent {
  id: string;
  title: string;
  description: string;
  occurred_at: string | null;
  time_precision: "datetime" | "date" | "month" | "year" | "unknown";
  source_ids: string[];
  evidence: TraceEvidence[];
  uncertainty: string | null;
}

export interface EventTraceResponse {
  trace_id: string;
  selection: TraceSelection;
  selected_event: TraceHotEvent;
  subject: string | null;
  status: "completed" | "partial";
  search_rounds: number;
  search_queries: string[][];
  suggested_queries: string[];
  timeline: TraceTimelineEvent[];
  sources: TraceSource[];
  missing_aspects: string[];
  warnings: string[];
}
