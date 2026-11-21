import { MessageSquare, Plus, X, RotateCcw, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { type Ref, useEffect, useRef } from "react";
import Markdown from "react-markdown";
import { BrandMark } from "@/components/ui/brand";
import type { Artifact, ChatMessage } from "@/types/agent";

function sourceUrl(value?: string) {
  try {
    const u = new URL(value ?? "");
    if (["http:", "https:"].includes(u.protocol) && !u.username && !u.password)
      return u.href;
  } catch {}
  return undefined;
}
interface Props {
  open: boolean;
  messages: ChatMessage[];
  closeRef: Ref<HTMLButtonElement>;
  onClose: () => void;
  busy: boolean;
  contextLabel: string;
  initError: string;
  onReload: () => void;
  onRetry: () => void;
  onNew: () => void;
  onClear: () => void;
  clearing: boolean;
  clearError: string;
  onView: (artifact: Artifact) => void;
}
export function ChatPanel({
  open,
  messages,
  closeRef,
  onClose,
  busy,
  contextLabel,
  initError,
  onReload,
  onRetry,
  onNew,
  onClear,
  clearing,
  clearError,
  onView,
}: Props) {
  const history = useRef<HTMLDivElement>(null),
    follow = useRef(true);
  useEffect(() => {
    const list = history.current;
    if (!messages.length) follow.current = true;
    if (open && list && follow.current) list.scrollTop = list.scrollHeight;
  }, [messages, open]);
  return (
    <aside
      id="agent-panel"
      className="chat-panel"
      aria-label="AI 事件助手"
      aria-hidden={!open}
      inert={!open}
    >
      <div className="chat-heading">
        <MessageSquare
          size={16}
          className="chat-heading-icon"
          aria-hidden="true"
        />
        <h2>事件对话</h2>
        <span className="chat-mode">Copilot</span>
        <button type="button" className="icon-button" aria-label="清空聊天记录"
          title={clearing ? "正在清空…" : "清空聊天记录"} disabled={busy || clearing || !messages.length}
          onClick={() => {
            if (window.confirm("确定清空当前对话的聊天记录与对话上下文吗？清空后无法恢复。已生成的分析报告和后台任务会保留。")) onClear();
          }}>
          <Trash2 size={16}/>
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="新建对话"
          title="新建独立对话"
          disabled={busy || clearing}
          onClick={onNew}
        >
          <Plus size={17} />
        </button>
        <button
          type="button"
          ref={closeRef}
          className="icon-button"
          title="收起 AI 侧栏"
          aria-label="收起 AI 侧栏"
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </div>
      <p className="copilot-page-context">正在参考：{contextLabel}</p>
      {clearError && <p className="copilot-page-context copilot-error" role="alert">{clearError}</p>}
      <div
        className="chat-history"
        role="log"
        aria-label="对话历史"
        ref={history}
        onScroll={() => {
          const l = history.current;
          if (l)
            follow.current = l.scrollHeight - l.clientHeight - l.scrollTop < 56;
        }}
      >
        {initError && (
          <div className="copilot-error" role="alert">
            {initError}
            <button className="outline-button" onClick={onReload}>
              重新连接
            </button>
          </div>
        )}
        {!messages.length && (
          <div className="chat-empty">
            <h3>从一个问题开始</h3>
            <p>
              可以直接询问当前热榜，也可以带入热点继续调查。已有分析会优先复用。
            </p>
          </div>
        )}
        {messages.map((m, index) => (
          <motion.article
            key={m.id}
            className="chat-message"
            data-role={m.role}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
          >
            {m.role === "assistant" && (
              <div className="assistant-byline">
                <BrandMark assistant />
                <strong>EventLens Copilot</strong>
              </div>
            )}
            {m.topic && <div className="message-context">{m.topic.title}</div>}
            {m.content && (
              <div className="copilot-markdown">
                <Markdown
                  skipHtml
                  components={{
                    a: ({ href, children }) =>
                      sourceUrl(href) ? (
                        <a
                          href={sourceUrl(href)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {children}
                        </a>
                      ) : (
                        <span>{children}</span>
                      ),
                    img: () => null,
                  }}
                >
                  {m.content}
                </Markdown>
              </div>
            )}
            {["pending", "streaming"].includes(m.status ?? "") && (
              <p className="chat-loading" role="status">
                <span />
                <span />
                <span />
                {m.tools?.findLast((t) => t.status === "running")?.label ??
                  "正在整理回答"}
                …
              </p>
            )}
            {!!m.tools?.length && (
              <details className="copilot-tool-record">
                <summary>工具记录 · {m.tools.length}</summary>
                <ul>
                  {m.tools.map((t) => (
                    <li key={t.id}>
                      {t.label} ·{" "}
                      {t.status === "running"
                        ? "进行中"
                        : t.status === "error"
                          ? "未完成"
                          : "调用完成"}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {!!m.sources?.length && (
              <details className="copilot-sources">
                <summary>资料来源 · {m.sources.length}</summary>
                <ul>
                  {m.sources.map((s, i) => (
                    <li key={i}>
                      {sourceUrl(s.url) ? (
                        <a
                          href={sourceUrl(s.url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {s.title || s.url}
                        </a>
                      ) : (
                        s.title
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {m.artifacts?.map((a) => (
              <button
                type="button"
                className="copilot-artifact"
                key={a.id}
                onClick={() => onView(a)}
              >
                <strong>
                  {a.kind === "trace" ? "事件溯源" : "公众舆情分析"}
                </strong>
                <span>{a.title}</span>
                <small>查看分析结果与实际进度 →</small>
              </button>
            ))}
            {m.status === "error" && (
              <p role="alert" className="copilot-error">
                {m.error ?? "回答未完成，请重试"}
              </p>
            )}
            {m.status === "cancelled" && (
              <p className="copilot-page-context">
                已停止回答。已启动的后台分析可在结果窗口单独查看或取消。
              </p>
            )}
            {index === messages.length - 1 &&
              !busy &&
              ["error", "cancelled"].includes(m.status ?? "") && (
                <button
                  type="button"
                  className="outline-button"
                  disabled={clearing}
                  onClick={onRetry}
                >
                  <RotateCcw size={13} />
                  重试此问题
                </button>
              )}
          </motion.article>
        ))}
      </div>
      <div className="chat-composer-space" aria-hidden="true" />
    </aside>
  );
}
