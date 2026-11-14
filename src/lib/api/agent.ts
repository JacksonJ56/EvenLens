import { mockReply } from "@/mocks/agent";
import type { AgentEvent, AgentRequest } from "@/types/agent";
import { delay } from "./delay";

export interface AgentApi {
  stream(request: AgentRequest, signal?: AbortSignal): AsyncIterable<AgentEvent>;
}

export const agentApi: AgentApi = {
  async *stream(request, signal) {
    await delay(720, signal);
    for (const text of mockReply(request)) {
      await delay(95, signal);
      yield { type: "delta", text };
    }
    yield { type: "done" };
  },
};
