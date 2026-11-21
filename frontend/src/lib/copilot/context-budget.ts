import type { AgentMessage } from "@earendil-works/pi-agent-core";

// Keep the existing byte-budget semantics. These are not provider-billed tokens.
export const OUTPUT_RESERVE = 2048;
export const HISTORY_BYTES = 12000;
export const TOOL_RESULT_BYTES = 6000;
export const FINAL_INSTRUCTION =
  "本轮资料获取已结束。现在必须直接根据已有资料回答用户，不再调用任何工具。不足之处明确说明，后台任务只报告真实状态，不得编造研究结论。";

export function clipText(text: string, bytes: number): string {
  if (Buffer.byteLength(text) <= bytes) return text;
  const suffix = "\n[内容已截取，缺失部分须重新核对]";
  const room = Math.max(0, bytes - Buffer.byteLength(suffix));
  let used = 0,
    result = "";
  for (const char of text) {
    const size = Buffer.byteLength(char);
    if (used + size > room) break;
    result += char;
    used += size;
  }
  return room ? result + suffix : "";
}

function compactMessage(
  message: AgentMessage,
  history: boolean,
  toolBytes = TOOL_RESULT_BYTES,
): AgentMessage {
  if (message.role === "toolResult") {
    // UI citations/artifacts are persisted separately. Do not resend details,
    // structured duplicates or execution metadata to the model on every turn.
    const {
      details: _details,
      usage: _usage,
      nestedCalls: _nested,
      durationMs: _duration,
      ...rest
    } = message;
    const text = message.content
      .flatMap((block) => (block.type === "text" ? [block.text] : []))
      .join("\n");
    return {
      ...rest,
      content: [
        { type: "text", text: clipText(text, history ? 1600 : toolBytes) },
      ],
    };
  }
  if (message.role === "assistant") {
    const content: typeof message.content = [];
    for (const block of message.content) {
      if (block.type === "thinking") continue;
      content.push(
        block.type === "text"
          ? {
              ...block,
              text: history ? clipText(block.text, 6000) : block.text,
            }
          : block,
      );
    }
    return { ...message, content };
  }
  if (history && message.role === "user") {
    if (typeof message.content === "string")
      return { ...message, content: clipText(message.content, 4000) };
    return {
      ...message,
      content: message.content.map((block) =>
        block.type === "text"
          ? { ...block, text: clipText(block.text, 4000) }
          : block,
      ),
    };
  }
  return message;
}

export function trimHistory(
  history: AgentMessage[],
  limit = HISTORY_BYTES,
): AgentMessage[] {
  const groups: AgentMessage[][] = [];
  for (const message of history) {
    if (message.role === "system") continue;
    if (message.role === "user") groups.push([]);
    if (!groups.length) continue; // Never start a transcript with orphan tool results.
    groups[groups.length - 1].push(compactMessage(message, true));
  }
  const chosen: AgentMessage[][] = [];
  let size = 0;
  for (const group of groups.reverse().slice(0, 8)) {
    let bytes = Buffer.byteLength(JSON.stringify(group));
    if (bytes > limit && !chosen.length) {
      // A large research turn must not erase the latest discussion entirely.
      // Keep actual user/final-answer text; remove every tool call and result as
      // a unit rather than leaving dangling call IDs in the transcript.
      const user = group[0];
      const last = group.findLast(
        (m) =>
          m.role === "assistant" && m.content.some((b) => b.type === "text"),
      );
      const minimal =
        last?.role === "assistant"
          ? [
              user,
              {
                ...last,
                content: last.content
                  .filter((b) => b.type === "text")
                  .map((b) => ({ ...b, text: clipText(b.text, 4000) })),
              },
            ]
          : [user];
      bytes = Buffer.byteLength(JSON.stringify(minimal));
      if (bytes <= limit) {
        chosen.unshift(minimal);
        size += bytes;
      }
      break;
    }
    if (size + bytes > limit) break;
    chosen.unshift(group);
    size += bytes;
  }
  return chosen.flat();
}

// Count only conversational payload and declarations once, not the executable
// tools registry, UI details, provider usage, timestamps or SDK runtime state.
export function requestBytes(messages: AgentMessage[]): number {
  return (
    512 +
    Buffer.byteLength(
      JSON.stringify(
        messages.map((message) => {
          if (message.role === "system")
            return {
              role: message.role,
              content: message.content,
              toolsAdded: message.toolsAdded,
              toolsRemoved: message.toolsRemoved,
            };
          if (message.role === "toolResult")
            return {
              role: message.role,
              toolCallId: message.toolCallId,
              content: message.content,
            };
          return { role: message.role, content: message.content };
        }),
      ),
    )
  );
}

export function fitContext(
  messages: AgentMessage[],
  page: AgentMessage,
  limit: number,
  finalizing: boolean,
) {
  const boundary = messages.indexOf(page);
  if (boundary < 0) throw new Error("COPILOT_CONTEXT_MARKER");
  const prefix = messages.slice(0, boundary).filter((m) => m.role === "system");
  let history = trimHistory(messages.slice(0, boundary));
  let current = messages.slice(boundary).map((m) => compactMessage(m, false));
  const finish: AgentMessage[] = finalizing
    ? [{ role: "system", content: FINAL_INSTRUCTION, timestamp: Date.now() }]
    : [];
  const assemble = () => [...prefix, ...history, ...current, ...finish];
  while (history.length && requestBytes(assemble()) > limit) {
    const next = history.findIndex(
      (m, index) => index > 0 && m.role === "user",
    );
    history = next < 0 ? [] : history.slice(next);
  }
  if (requestBytes(assemble()) > limit) {
    // Keep all call/result pairs. Only shorten result text, never tool arguments,
    // the user's current question or the verified current-page snapshot.
    current = current.map((m) => compactMessage(m, false, 1600));
  }
  const result = assemble();
  return { messages: result, bytes: requestBytes(result) };
}
