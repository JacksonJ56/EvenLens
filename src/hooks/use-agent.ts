"use client";

import { useEffect, useRef, useState } from "react";
import { agentApi } from "@/lib/api/agent";
import type { ChatMessage, SkillId } from "@/types/agent";
import type { BoardQuery, Trend } from "@/types/trending";

export function useAgent(board: BoardQuery) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [skill, setSkill] = useState<SkillId>();
  const [topic, setTopic] = useState<Trend>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function send() {
    const question = draft.trim();
    if (!question || active.current) return;

    const controller = new AbortController();
    active.current = controller;
    const user: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question, skill, topic };
    const answer: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "", status: "pending" };

    function update(change: (message: ChatMessage) => ChatMessage) {
      setMessages((current) => current.map((message) => message.id === answer.id ? change(message) : message));
    }

    setMessages((current) => [...current, user, answer]);
    setOpen(true);
    setDraft("");
    setTopic(undefined);

    try {
      for await (const event of agentApi.stream({ question, skill, topic, board, history: messages }, controller.signal)) {
        if (event.type === "delta") {
          update((message) => ({ ...message, content: message.content + event.text, status: "streaming" }));
        }
      }
      update((message) => ({ ...message, status: "done" }));
    } catch {
      if (!controller.signal.aborted) update((message) => ({ ...message, status: "error" }));
    } finally {
      if (active.current === controller) active.current = null;
    }
  }

  return {
    open, setOpen, draft, setDraft, skill, setSkill, topic, setTopic, messages, send,
    busy: messages.some(({ status }) => status === "pending" || status === "streaming"),
  };
}
