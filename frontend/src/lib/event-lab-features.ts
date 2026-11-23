import { Aperture, Radar, type LucideIcon } from "lucide-react";
import type { EventLabEventContext } from "@/types/event-lab";
import type { EventTraceResponse } from "@/types/event-trace";
import { requestEventTrace } from "./api/event-trace";
import { requestPublicOpinion } from "./api/public-opinion";
import type { OpinionProgress, OpinionReport } from "@/types/public-opinion";

export interface EventLabTaskRequest {
  event: EventLabEventContext;
  featureId: string;
  datasetId?: string;
  resumeTaskId?: string;
}

export type EventLabTaskResult = { mode: "live"; trace: EventTraceResponse } | { mode: "opinion"; report: OpinionReport };

export interface EventLabFeature {
  id: string;
  name: string;
  icon: LucideIcon;
  description?: string;
  mode: EventLabTaskResult["mode"];
  execute: (request: EventLabTaskRequest, signal: AbortSignal, onProgress?: (update: OpinionProgress) => void) => Promise<EventLabTaskResult>;
}

export const eventLabFeatures = [
  {
    id: "event_tracing", name: "事件溯源", icon: Aperture, mode: "live",
    async execute({ event }, signal) {
      return { mode: "live", trace: await requestEventTrace(event, signal) };
    },
  },
  { id: "public_opinion", name: "公众舆情分析", icon: Radar, mode: "opinion",
    async execute({ event, datasetId, resumeTaskId }, signal, onProgress) {
      return { mode: "opinion", report: await requestPublicOpinion(event, signal, onProgress, datasetId, resumeTaskId) };
    } },
] as const satisfies readonly [EventLabFeature, ...EventLabFeature[]];
