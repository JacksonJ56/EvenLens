import { Aperture, Blocks, Radar, type LucideIcon } from "lucide-react";
import type { EventLabEventContext } from "@/types/event-lab";
import type { EventTraceResponse } from "@/types/event-trace";
import { delay } from "./api/delay";
import { requestEventTrace } from "./api/event-trace";

export interface EventLabTaskRequest {
  event: EventLabEventContext;
  featureId: string;
}

export type EventLabTaskResult = { mode: "demo" } | { mode: "live"; trace: EventTraceResponse };

export interface EventLabFeature {
  id: string;
  name: string;
  icon: LucideIcon;
  description?: string;
  mode: EventLabTaskResult["mode"];
  execute: (request: EventLabTaskRequest, signal: AbortSignal) => Promise<EventLabTaskResult>;
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
  { id: "experiment-2", name: "实验功能二", icon: Radar, mode: "demo", execute: previewExecution },
  { id: "experiment-3", name: "实验功能三", icon: Blocks, mode: "demo", execute: previewExecution },
] as const satisfies readonly [EventLabFeature, ...EventLabFeature[]];
