import { MessageSquare, X } from "lucide-react";
import { motion } from "motion/react";
import { type Ref, useEffect, useRef } from "react";
import { BrandMark } from "@/components/ui/brand";
import { getSkill } from "@/lib/catalog";
import type { ChatMessage } from "@/types/agent";

export function ChatPanel({ open, messages, closeRef, onClose }: { open: boolean; messages: ChatMessage[]; closeRef: Ref<HTMLButtonElement>; onClose: () => void }) {
  const history = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    const list = history.current;
    if (open && list && follow.current) list.scrollTop = list.scrollHeight;
  }, [messages, open]);

  return (
    <aside id="agent-panel" className="chat-panel" aria-label="AI 事件助手" aria-hidden={!open} inert={!open}>
      <div className="chat-heading">
        <MessageSquare size={16} className="chat-heading-icon" aria-hidden="true" />
        <h2>事件对话</h2>
        <span className="chat-mode">模拟</span>
        <button type="button" ref={closeRef} className="icon-button" title="收起 AI 侧栏" aria-label="收起 AI 侧栏" onClick={onClose}><X size={17} /></button>
      </div>
      <div className="chat-history" role="log" aria-label="对话历史" ref={history} onScroll={() => {
        const list = history.current;
        if (list) follow.current = list.scrollHeight - list.clientHeight - list.scrollTop < 56;
      }}>
        {messages.length === 0 && (
          <div className="chat-empty"><h3>从一个热点开始</h3><p>直接输入问题，或用榜单右侧的对话图标带入一个热点。</p></div>
        )}
        {messages.map((message) => (
          <motion.article key={message.id} className="chat-message" data-role={message.role} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
            {message.role === "assistant" && <div className="assistant-byline"><BrandMark assistant /><strong>事件助手</strong></div>}
            {message.role === "user" && (message.skill || message.topic) && <div className="message-context">{[getSkill(message.skill)?.shortLabel, message.topic?.title].filter(Boolean).join(" · ")}</div>}
            {message.status === "pending" ? (
              <p className="chat-loading" role="status"><span /><span /><span />正在整理分析思路</p>
            ) : (
              <>
                {message.content && <p>{message.content}</p>}
                {message.status === "error" && <p role="alert">模拟回复中断，请重新发送问题。</p>}
              </>
            )}
          </motion.article>
        ))}
      </div>
      <div className="chat-composer-space" aria-hidden="true" />
    </aside>
  );
}
