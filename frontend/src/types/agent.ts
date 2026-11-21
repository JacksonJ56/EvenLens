import type { BoardQuery, CategoryId, Trend } from "./trending";
export interface PageContext {
  category_id: CategoryId;
  platform_id: BoardQuery["platform"];
  feed_id: string;
  mode: "mock" | "live";
  selected_event_id?: string;
  items: Pick<Trend, "id" | "title" | "rank">[];
}
export interface HotspotReference {
  category_id: CategoryId;
  platform_id: BoardQuery["platform"];
  feed_id: string;
  id: string;
}
export interface Source {
  title: string;
  url: string;
}
export interface Artifact {
  id: string;
  kind: "trace" | "opinion";
  title: string;
  status: string;
  message: string;
  created_at: number;
}
export interface ToolState {
  id: string;
  name: string;
  label: string;
  status: "running" | "done" | "error";
}
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  topic?: Pick<Trend, "id" | "title">;
  status?: "pending" | "streaming" | "done" | "error" | "cancelled";
  error?: string;
  tools?: ToolState[];
  sources?: Source[];
  artifacts?: Artifact[];
}
export interface AgentRequest {
  thread_id: string;
  request_id: string;
  user_id: string;
  question: string;
  page: PageContext;
  reference?: HotspotReference;
}
export type AgentEvent =
  | { type: "start"; thread_id: string }
  | { type: "delta"; text: string }
  | { type: "tool"; tool: ToolState }
  | { type: "sources"; sources: Source[] }
  | { type: "artifact"; artifact: Artifact }
  | { type: "error"; message: string }
  | { type: "done"; status: "done" | "error" | "cancelled" };
