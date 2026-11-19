import type { EventLabEventContext } from "@/types/event-lab";
import type { OpinionCapabilities, OpinionProgress, OpinionReport } from "@/types/public-opinion";
import { delay } from "./delay";
import { eventPayload } from "./event-trace";

export async function opinionAPI<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/public-opinion/${path}`, { cache: "no-store", ...init });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : undefined;
    throw new Error(typeof detail === "string" ? detail : `舆情服务请求失败（${response.status}）`);
  }
  return data as T;
}

export function getOpinionCapabilities(signal?: AbortSignal) {
  return opinionAPI<OpinionCapabilities>("capabilities", { signal });
}

export async function importOpinionComments(event: EventLabEventContext, file: File, authorized: boolean, signal?: AbortSignal) {
  if (file.size > 4_000_000) throw new Error("评论文件须小于 4 MB");
  if (!authorized) throw new Error("请确认拥有这些评论的合法使用授权");
  const { selection, event: selected } = eventPayload(event);
  return opinionAPI<{ dataset_id: string; stats: OpinionReport["stats"] }>("datasets/import", {
    method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selection, event: selected, format: file.name.toLowerCase().endsWith(".csv") ? "csv" : "json",
      content: await file.text(), authorized }),
  });
}

export async function requestPublicOpinion(event: EventLabEventContext, signal: AbortSignal,
  progress?: (update: OpinionProgress) => void, datasetId?: string, resumeTaskId?: string): Promise<OpinionReport> {
  const payload = eventPayload(event);
  // Finish the short create request even if the user cancels; once its ID is known, cancel it too.
  let task = resumeTaskId ? await opinionAPI<OpinionProgress>(`tasks/${encodeURIComponent(resumeTaskId)}`, {
    signal: AbortSignal.timeout(20000),
  }) : await opinionAPI<OpinionProgress>("tasks", {
    method: "POST", signal: AbortSignal.timeout(20000), headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, function_id: "public_opinion",
      dataset_id: datasetId ?? null, idempotency_key: crypto.randomUUID() }),
  });
  if (resumeTaskId && ["failed", "cancelled", "interrupted"].includes(task.status)) {
    task = await opinionAPI<OpinionProgress>(`tasks/${encodeURIComponent(resumeTaskId)}/resume`, {
      method: "POST", signal: AbortSignal.timeout(20000),
    });
  }
  const cancel = () => { void opinionAPI(`tasks/${task.id}`, { method: "DELETE", keepalive: true }).catch(() => undefined); };
  if (signal.aborted) { cancel(); signal.throwIfAborted(); }
  signal.addEventListener("abort", cancel, { once: true });
  try {
    let update = task;
    for (;;) {
      signal.throwIfAborted();
      progress?.(update);
      if (update.status === "completed" || update.status === "partial") break;
      if (["failed", "cancelled", "interrupted"].includes(update.status)) throw new Error(update.message);
      await delay(1000, signal);
      for (let attempt = 0; ; attempt++) {
        try { update = await opinionAPI<OpinionProgress>(`tasks/${task.id}`, { signal }); break; }
        catch (error) { if (attempt >= 2 || signal.aborted) throw error; await delay(1000, signal); }
      }
    }
    const report = await opinionAPI<OpinionReport>(`tasks/${task.id}/report`, { signal });
    if (report.task_id !== task.id || report.selected_event.id !== event.trendId || report.selection.platform_id !== event.platformId ||
        report.selection.feed_id !== event.feedId || report.selection.category_id !== event.categoryId || !Array.isArray(report.sections)) {
      throw new Error("舆情报告与当前热点选择不匹配");
    }
    return report;
  } finally { signal.removeEventListener("abort", cancel); }
}
