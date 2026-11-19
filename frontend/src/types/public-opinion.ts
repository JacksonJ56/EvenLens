import type { EventTraceResponse } from "./event-trace";

export interface PlatformCapability {
  supported: boolean;
  adapter_implemented: boolean;
  collector_ready: boolean;
  message: string;
}
export interface OpinionCapabilities {
  platforms: Record<string, PlatformCapability>;
  import_available: boolean;
  llm_configured: boolean;
}
export interface OpinionProgress {
  id: string;
  status: "queued" | "running" | "completed" | "partial" | "failed" | "cancelled" | "interrupted";
  stage: string;
  message: string;
  updated_at: string;
  usage: Record<string, number>;
  history?: { stage: string; message: string; at: string }[];
}
export interface CommentEvidence { post_id: string; comment_id: string }
export interface OpinionComment extends CommentEvidence {
  content: string;
  raw_content?: string;
  is_preview?: boolean;
  source_rank: number | null;
  sort_mode: string;
  source_url: string | null;
  created_at: string | null;
  like_count: number | null;
}
export interface OpinionSection {
  type: "discussion_topics" | "public_emotions" | "opinion_clusters" | "stance_analysis" | "controversies" | "trends" | "representative_comments" | "contextual_insights";
  title: string;
  status: "completed" | "not_applicable" | "insufficient_data" | "failed";
  summary: string;
  reason: string | null;
  sample_size: number | null;
  issue?: string | null;
  evidence: CommentEvidence[];
  data: { label: string; explanation: string; count: number; percent: number | null; evidence: CommentEvidence[] }[];
  contextual_insights: {
    title: string; dimension: string; explanation: string;
    classification: "verified_fact" | "supported_inference" | "unverified_hypothesis" | "insufficient_evidence";
    source_ids: string[]; time_range: string | null; uncertainty: string;
    evidence: { source_id: string; excerpt: string }[];
  }[];
}
export interface OpinionReport {
  task_id: string;
  dataset_id: string;
  selection: EventTraceResponse["selection"];
  selected_event: EventTraceResponse["selected_event"];
  generated_at: string;
  status: "completed" | "partial";
  overall_assessment: OverallAssessment;
  chart_interpretations?: ChartInterpretation[];
  stats: {
    post_count: number; collected_count: number; analyzed_count: number; prepared_count: number; reply_count: number;
    contributing_post_count?: number;
    per_post: Record<string, number>; sort_modes: string[]; time_start: string | null; time_end: string | null;
    input_count: number; origin: "imported" | "collected";
    limitations: string[];
  };
  sections: OpinionSection[];
  posts: { id: string; title: string; url: string; platform_id: string }[];
  sources: { id: string; title: string; url: string; published_at: string | null; access: "summary" | "body" }[];
  limitations: string[];
  usage: Record<string, number>;
  charts?: OpinionChart[];
  context_timeline?: OpinionContextNode[];
  visualization_notes?: Record<string, string>;
}

export interface OverallAssessment {
  summary: string; core_judgment: string | null; key_findings: string[];
  section_types: OpinionSection["type"][]; evidence: CommentEvidence[]; source_ids: string[];
  status: "completed" | "partial" | "legacy" | "unavailable"; reason: string | null;
}
export interface ChartInterpretation {
  chart_id: string; analysis: string; evidence: CommentEvidence[]; source_ids: string[];
}

export type OpinionChartType = "emotion_distribution" | "discussion_topics" | "stance_comparison" | "comment_timeline" | "post_contribution" | "discussion_radar";
export interface OpinionChartPoint {
  id: string; label: string; count: number; percent: number | null;
  explanation: string; evidence: CommentEvidence[];
  start_at: string | null; end_at: string | null;
  metric_definition?: string | null;
}
export interface OpinionChart {
  id: string; type: OpinionChartType; title: string; description: string;
  sample_size: number; unit: "条" | "%"; points: OpinionChartPoint[];
  overlapping: boolean; issue: string | null; timezone: string | null; granularity: string | null;
  normalization?: "comment_share" | null;
}
export interface OpinionContextNode {
  id: string; kind: "capture" | "post" | "source" | "insight"; title: string; description: string;
  occurred_at: string | null; time_label: string; classification: string | null;
  source_ids: string[]; evidence: { source_id: string; excerpt: string }[]; uncertainty: string;
  post_id?: string | null;
}
export interface ChartCommentPage { comments: OpinionComment[]; total: number; offset: number; limit: number }

export interface PlatformSession {
  platform_id: string;
  status: "not_logged_in" | "unverified" | "checking" | "logging_in" | "verified" | "expired" | "unavailable" | "error" | "cancelled";
  message: string;
  configured: boolean;
  session_verified: boolean;
  collector_ready: boolean;
  runtime_ready: boolean;
  login_available: boolean;
  remote_verification_supported: boolean;
  job_id: string | null;
  checked_at: string | null;
}
