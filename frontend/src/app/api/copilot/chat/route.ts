import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { connection, errorResponse, localAction } from "@/lib/copilot/http";
import { requestSchema, canonicalPage, boardCatalog } from "@/lib/copilot/contracts";
import { runCopilot } from "@/lib/copilot/runtime";
import type { AgentEvent, ChatMessage } from "@/types/agent";
export const runtime = "nodejs";
export const maxDuration = 150;
export async function POST(request: Request) {
  try {
    localAction(request);
    if (Number(request.headers.get("content-length")) > 30000)
      return Response.json({ detail: "问题或页面上下文过长" }, { status: 413 });
    const raw = await request.text();
    if (raw.length > 30000)
      return Response.json({ detail: "请求过长" }, { status: 413 });
    const parsed = requestSchema.safeParse(JSON.parse(raw));
    if (!parsed.success)
      return Response.json(
        { detail: "对话参数无效，请刷新重试" },
        { status: 422 },
      );
    const input = parsed.data,
      page = canonicalPage(input.page);
    const referencePage = input.reference
      ? canonicalPage({
          ...input.page,
          category_id: input.reference.category_id,
          platform_id: input.reference.platform_id,
          feed_id: input.reference.feed_id,
        })
      : undefined;
    const { backend, config } = await connection();
    const begin = await backend.call<{
      history: AgentMessage[];
      messages: ChatMessage[];
      context: unknown;
    }>("begin", {
      thread_id: input.thread_id,
      request_id: input.request_id,
      page,
      reference: input.reference,
      reference_page: referencePage,
      selected_event_id: input.page.selected_event_id,
      mode: input.page.mode,
      catalog: boardCatalog(),
    });
    const controller = new AbortController();
    const stop = () => controller.abort();
    request.signal.addEventListener("abort", stop, { once: true });
    const timer = setTimeout(() => controller.abort(new Error("COPILOT_TIMEOUT")), config.timeoutMs);
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(sink) {
        const emit = (event: AgentEvent) => {
          try {
            sink.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
          } catch {
            /* Client disconnected; state is still settled below. */
          }
        };
        const progress = (event: AgentEvent) => {
          if (event.type !== "done") emit(event);
        };
        const heartbeat = setInterval(() => {
          try {
            sink.enqueue(encoder.encode(": heartbeat\n\n"));
          } catch {
            stop();
          }
        }, 10000);
        emit({ type: "start", thread_id: input.thread_id });
        void (async () => {
          try {
            const result = await runCopilot(
              {
                question: input.question,
                context: begin.context,
                history: begin.history,
                threadId: input.thread_id,
                requestId: input.request_id,
              },
              config,
              backend,
              progress,
              controller.signal,
            );
            const saved = await backend.call<{ messages: ChatMessage[] }>(
              "threads?id=" + input.thread_id,
            );
            const context = begin.context as {
              reference?: { id: string; title: string } | null;
            };
            const user: ChatMessage = {
              id: input.user_id,
              role: "user",
              content: input.question,
              topic: context.reference
                ? { id: context.reference.id, title: context.reference.title }
                : undefined,
            };
            const answer: ChatMessage = {
              id: input.request_id,
              role: "assistant",
              content: result.answer,
              status: result.status,
              error: result.error,
              tools: result.tools,
              sources: result.sources,
              artifacts: result.artifacts,
            };
            const messages = [
              ...saved.messages.filter(
                (m) => m.id !== user.id && m.id !== answer.id,
              ),
              user,
              answer,
            ].slice(-80);
            while (
              messages.length > 2 &&
              Buffer.byteLength(JSON.stringify(messages)) > 135000
            )
              messages.splice(0, 2);
            const settled = await backend.call<{ saved: boolean }>("finish", {
              thread_id: input.thread_id,
              request_id: input.request_id,
              history: result.history,
              messages,
            });
            if (!settled.saved) throw new Error("Conversation lease expired");
            emit({ type: "done", status: result.status });
          } catch {
            emit({
              type: "error",
              message: "会话保存或业务服务中断，请重新读取后重试",
            });
            emit({ type: "done", status: "error" });
            await backend
              .call("finish", {
                thread_id: input.thread_id,
                request_id: input.request_id,
                history: begin.history,
                messages: begin.messages,
              })
              .catch(() => undefined);
          } finally {
            clearTimeout(timer);
            clearInterval(heartbeat);
            request.signal.removeEventListener("abort", stop);
            try {
              sink.close();
            } catch {}
          }
        })();
      },
      cancel() {
        stop();
      },
    });
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
