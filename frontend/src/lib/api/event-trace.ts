import type { EventLabEventContext } from "@/types/event-lab";
import type { EventTraceResponse, TraceRequest } from "@/types/event-trace";

export function eventPayload(event: EventLabEventContext): TraceRequest {
  return {
    function_id: "event_tracing",
    selection: {
      category_id: event.categoryId, category_name: event.categoryName,
      platform_id: event.platformId, platform_name: event.platformName,
      feed_id: event.feedId, board_id: event.boardId ?? null, board_name: event.boardName ?? null,
    },
    event: {
      id: event.trendId, title: event.title, url: event.url ?? null,
      summary: event.trend.preview?.summary ?? null, rank: event.trend.rank ?? null,
      captured_at: event.capturedAt ?? null,
    },
  };
}

export async function requestEventTrace(event: EventLabEventContext, signal: AbortSignal): Promise<EventTraceResponse> {
  const payload = eventPayload(event);
  const response = await fetch("/api/event-trace", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    cache: "no-store", signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof data?.detail === "string" ? data.detail :
      response.status === 422 ? "热点选择数据无效，请刷新并重新选择" : `事件溯源请求失败（${response.status}）`;
    throw new Error(message);
  }
  if (data?.selected_event?.id !== event.trendId || data?.selection?.feed_id !== event.feedId ||
      data?.selection?.platform_id !== event.platformId || data?.selection?.category_id !== event.categoryId ||
      !["completed", "partial"].includes(data.status) || !Array.isArray(data.timeline) ||
      !Array.isArray(data.sources) || !Array.isArray(data.missing_aspects) ||
      !Array.isArray(data.suggested_queries) || !Array.isArray(data.warnings)) {
    throw new Error("事件溯源响应与当前热点不匹配或格式无效");
  }
  return data as EventTraceResponse;
}
