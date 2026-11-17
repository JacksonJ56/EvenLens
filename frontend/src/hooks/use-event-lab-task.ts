import { useCallback, useEffect, useRef, useState } from "react";
import type { EventLabFeature, EventLabTaskRequest, EventLabTaskResult } from "@/lib/event-lab-features";

interface TaskRun {
  id: number;
  feature: EventLabFeature;
  request: EventLabTaskRequest;
}

export type EventLabTaskState = TaskRun & (
  | { status: "running" }
  | { status: "complete"; result: EventLabTaskResult }
  | { status: "error"; message: string }
);

export function useEventLabTask() {
  const [task, setTask] = useState<EventLabTaskState>();
  const inFlight = useRef<AbortController>(null);
  const runId = useRef(0);

  useEffect(() => () => { inFlight.current?.abort(); }, []);

  const cancel = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
    setTask(undefined);
  }, []);

  async function run(feature: EventLabFeature, request: EventLabTaskRequest) {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    const run = { id: ++runId.current, feature, request };
    setTask({ ...run, status: "running" });

    try {
      const result = await feature.execute(request, controller.signal);
      if (!controller.signal.aborted) setTask({ ...run, status: "complete", result });
    } catch (error) {
      if (!controller.signal.aborted) {
        setTask({ ...run, status: "error", message: error instanceof Error ? error.message : "任务执行失败，请重试" });
      }
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
  }

  return { task, run, cancel };
}
