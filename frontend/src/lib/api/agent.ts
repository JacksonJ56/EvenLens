import type { AgentEvent, AgentRequest } from "@/types/agent";
import { eventSchema } from "@/lib/copilot/contracts";

export interface AgentApi {
  stream(
    request: AgentRequest,
    signal?: AbortSignal,
  ): AsyncIterable<AgentEvent>;
}

export const agentApi: AgentApi = {
  async *stream(request, signal) {
    const response = await fetch("/api/copilot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? `对话请求失败（${response.status}）`);
    }
    if (!response.body) throw new Error("未取得回答数据流");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "",
      done = false;
    try {
      for (;;) {
        const part = await reader.read();
        buffer += decoder
          .decode(part.value, { stream: !part.done })
          .replace(/\r\n/g, "\n");
        if (buffer.length > 1000000) throw new Error("回答数据流过长");
        let end: number;
        while ((end = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);
          const data = frame
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trimStart())
            .join("\n");
          if (!data) continue;
          const event = eventSchema.parse(JSON.parse(data));
          if (event.type === "done") done = true;
          yield event;
        }
        if (part.done) break;
      }
      if (!done) throw new Error("连接已中断，回答可能未完成，请重试");
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  },
};
