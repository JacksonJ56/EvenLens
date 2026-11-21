"use client";
import { useEffect, useRef, useState } from "react";
import { agentApi } from "@/lib/api/agent";
import type {
  AgentRequest,
  ChatMessage,
  PageContext,
  HotspotReference,
} from "@/types/agent";
import type { Trend } from "@/types/trending";

export function useAgent(page: PageContext) {
  const [open, setOpen] = useState(false),
    [draft, setDraft] = useState(""),
    [topic, setReference] = useState<{
      trend: Trend;
      reference: HotspotReference;
    }>();
  const [messages, setMessages] = useState<ChatMessage[]>([]),
    [threadId, setThreadId] = useState<string>(),
    [busy, setBusy] = useState(false),
    [initError, setInitError] = useState(""),
    [clearing, setClearing] = useState(false),
    [clearError, setClearError] = useState("");
  const clearingActive = useRef(false);
  const latest = useRef(page);
  latest.current = page;
  const active = useRef<AbortController | null>(null),
    generation = useRef(0),
    last = useRef<
      | {
          question: string;
          user_id: string;
          reference?: HotspotReference;
          topic?: Trend;
        }
      | undefined
    >(undefined);
  async function initialize(fresh = false, signal?: AbortSignal) {
    if (clearingActive.current) return;
    const ticket = ++generation.current;
    setInitError("");
    setClearError("");
    setThreadId(undefined);
    try {
      let id = fresh ? null : localStorage.getItem("eventlens-copilot-thread");
      let response = await fetch(
        "/api/copilot/threads" + (id ? "?id=" + encodeURIComponent(id) : ""),
        { signal, cache: "no-store" },
      );
      if (response.status === 404) {
        localStorage.removeItem("eventlens-copilot-thread");
        id = null;
        response = await fetch("/api/copilot/threads", {
          signal,
          cache: "no-store",
        });
      }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "无法初始化对话");
      if (ticket !== generation.current || signal?.aborted) return;
      setThreadId(body.thread_id);
      setMessages(body.messages);
      localStorage.setItem("eventlens-copilot-thread", body.thread_id);
      if (fresh) {
        setReference(undefined);
        last.current = undefined;
      }
    } catch (e) {
      if (!signal?.aborted && ticket === generation.current)
        setInitError(e instanceof Error ? e.message : "无法读取对话");
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void initialize(false, controller.signal);
    return () => {
      controller.abort();
      active.current?.abort();
    };
  }, []);
  function setTopic(trend?: Trend) {
    setReference(
      trend
        ? {
            trend,
            reference: {
              category_id: latest.current.category_id,
              platform_id: latest.current.platform_id,
              feed_id: latest.current.feed_id,
              id: trend.id,
            },
          }
        : undefined,
    );
  }
  async function send(retry = false) {
    const pending = retry
      ? last.current
      : {
          question: draft.trim(),
          user_id: crypto.randomUUID(),
          reference: topic?.reference,
          topic: topic?.trend,
        };
    if (!pending?.question || active.current || clearingActive.current || !threadId) return;
    setClearError("");
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setOpen(true);
    last.current = pending;
    const answerId = crypto.randomUUID();
    const user: ChatMessage = {
      id: pending.user_id,
      role: "user",
      content: pending.question,
      topic: pending.topic,
    };
    setMessages(
      (current) =>
        [
          ...current.filter(
            (m) => !retry || (m.status !== "error" && m.status !== "cancelled"),
          ),
          ...(current.some((m) => m.id === user.id) ? [] : [user]),
          { id: answerId, role: "assistant", content: "", status: "pending" },
        ].slice(-80) as ChatMessage[],
    );
    if (!retry) {
      setDraft("");
      setReference(undefined);
    }
    const change = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((current) =>
        current.map((m) => (m.id === answerId ? fn(m) : m)),
      );
    try {
      const request: AgentRequest = {
        thread_id: threadId,
        request_id: answerId,
        user_id: pending.user_id,
        question: pending.question,
        page: latest.current,
        reference: pending.reference,
      };
      for await (const event of agentApi.stream(request, controller.signal)) {
        if (event.type === "delta")
          change((m) => ({
            ...m,
            content: m.content + event.text,
            status: "streaming",
          }));
        else if (event.type === "tool")
          change((m) => ({
            ...m,
            tools: [
              ...(m.tools ?? []).filter((t) => t.id !== event.tool.id),
              event.tool,
            ],
          }));
        else if (event.type === "sources")
          change((m) => ({
            ...m,
            sources: [...(m.sources ?? []), ...event.sources],
          }));
        else if (event.type === "artifact")
          change((m) => ({
            ...m,
            artifacts: [
              ...(m.artifacts ?? []).filter((a) => a.id !== event.artifact.id),
              event.artifact,
            ],
          }));
        else if (event.type === "error")
          change((m) => ({ ...m, status: "error", error: event.message }));
        else if (event.type === "done")
          change((m) => ({ ...m, status: event.status }));
      }
    } catch (e) {
      change((m) => ({
        ...m,
        status: controller.signal.aborted ? "cancelled" : "error",
        tools: m.tools?.map((t) =>
          t.status === "running" ? { ...t, status: "error" } : t,
        ),
        error: controller.signal.aborted
          ? undefined
          : e instanceof Error
            ? e.message
            : "回答中断，请重试",
      }));
    } finally {
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  async function clearHistory() {
    if (!threadId || active.current || clearingActive.current) return;
    clearingActive.current = true;
    setClearing(true);
    setClearError("");
    try {
      const response = await fetch("/api/copilot/threads?id="+encodeURIComponent(threadId), {method: "DELETE"});
      const body = await response.json();
      if (!response.ok || body.cleared !== true) throw new Error(body.detail ?? "清空失败，请重试");
      setMessages([]);
      last.current = undefined;
    } catch (error) {
      setClearError(error instanceof Error ? error.message : "清空失败，请重试");
    } finally {
      clearingActive.current = false;
      setClearing(false);
    }
  }
  return {
    open,
    setOpen,
    draft,
    setDraft,
    topic: topic?.trend,
    setTopic,
    messages,
    threadId,
    busy,
    clearing,
    clearError,
    clearHistory,
    initError,
    ready: !!threadId && !clearing,
    send: () => send(),
    retry: () => send(true),
    stop: () => active.current?.abort(),
    newConversation: () => {
      if (!active.current) void initialize(true);
    },
    reload: () => void initialize(),
  };
}
