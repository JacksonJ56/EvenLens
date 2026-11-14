import type { BoardQuery, Trend } from "./trending";

export type SkillId = "timeline" | "context" | "perspectives";

export interface Skill {
  id: SkillId;
  label: string;
  shortLabel: string;
  placeholder: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  skill?: SkillId;
  topic?: Trend;
  status?: "pending" | "streaming" | "done" | "error";
}

export interface AgentRequest {
  question: string;
  skill?: SkillId;
  topic?: Trend;
  board: BoardQuery;
  history: readonly ChatMessage[];
}

export type AgentEvent = { type: "delta"; text: string } | { type: "done" };
