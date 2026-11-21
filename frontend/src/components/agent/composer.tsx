import { ArrowUp, Square, X } from "lucide-react";
import type { FormEvent, Ref } from "react";
import type { Trend } from "@/types/trending";

interface ComposerProps {
  draft: string;
  topic?: Trend;
  busy: boolean;
  ready: boolean;
  inputRef: Ref<HTMLTextAreaElement>;
  onDraft: (draft: string) => void;
  onClearTopic: () => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({
  draft,
  topic,
  busy,
  ready,
  inputRef,
  onDraft,
  onClearTopic,
  onSend,
  onStop,
}: ComposerProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  return (
    <section className="composer" aria-label="AI 提问">
      <form className="composer-form" onSubmit={submit}>
        {topic && (
          <div className="composer-context">
            {topic && (
              <button
                type="button"
                onClick={onClearTopic}
                aria-label={`移除关联热点：${topic.title}`}
              >
                <span>{topic.title}</span>
                <X size={13} />
              </button>
            )}
          </div>
        )}
        <div className="composer-input-line">
          <textarea
            ref={inputRef}
            id="agent-draft"
            aria-label="输入 AI 问题"
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            placeholder="追问当前事件，或核对观点与证据…"
            rows={1}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing &&
                event.keyCode !== 229
              ) {
                event.preventDefault();
                if (ready && !busy && draft.trim()) onSend();
              }
            }}
          />
          {busy ? (
            <button
              type="button"
              className="send-button"
              aria-label="停止生成"
              title="停止回答；后台分析需单独取消"
              onClick={onStop}
            >
              <Square size={13} aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              className="send-button"
              aria-label="发送消息"
              title="发送消息"
              disabled={!ready || !draft.trim()}
            >
              <ArrowUp size={17} aria-hidden="true" />
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
