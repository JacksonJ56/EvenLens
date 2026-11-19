import { Aperture, Blocks, Radar, type LucideIcon } from "lucide-react";
import type { EventLabEventContext } from "@/types/event-lab";
import type { EventTraceResponse } from "@/types/event-trace";
import { delay } from "./api/delay";
import { requestEventTrace } from "./api/event-trace";
import { requestPublicOpinion } from "./api/public-opinion";
import type { OpinionProgress, OpinionReport } from "@/types/public-opinion";

export interface EventLabTaskRequest {
  event: EventLabEventContext;
  featureId: string;
  datasetId?: string;
  resumeTaskId?: string;
}

export type EventLabTaskResult = { mode: "demo" } | { mode: "live"; trace: EventTraceResponse } | { mode: "opinion"; report: OpinionReport };

export interface EventLabFeature {
  id: string;
  name: string;
  icon: LucideIcon;
  description?: string;
  mode: EventLabTaskResult["mode"];
  execute: (request: EventLabTaskRequest, signal: AbortSignal, onProgress?: (update: OpinionProgress) => void) => Promise<EventLabTaskResult>;
}

async function previewExecution(_request: EventLabTaskRequest, signal: AbortSignal): Promise<EventLabTaskResult> {
  await delay(1700, signal);
  return { mode: "demo" };
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
  { id: "experiment-3", name: "实验功能三", icon: Blocks, mode: "demo", execute: previewExecution },
] as const satisfies readonly [EventLabFeature, ...EventLabFeature[]];
