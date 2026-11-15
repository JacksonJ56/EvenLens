import { ArrowUp, GitBranch, ScanLine, UsersRound, X } from "lucide-react";
import type { FormEvent, Ref } from "react";
import { getSkill, skills } from "@/lib/catalog";
import type { SkillId } from "@/types/agent";
import type { Trend } from "@/types/trending";

const icons = { timeline: GitBranch, context: UsersRound, perspectives: ScanLine };

interface ComposerProps {
  draft: string;
  skill?: SkillId;
  topic?: Trend;
  busy: boolean;
  inputRef: Ref<HTMLTextAreaElement>;
  onDraft: (draft: string) => void;
  onSkill: (id?: SkillId) => void;
  onClearTopic: () => void;
  onSend: () => void;
}

export function Composer({ draft, skill, topic, busy, inputRef, onDraft, onSkill, onClearTopic, onSend }: ComposerProps) {
  const selected = getSkill(skill);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  return (
    <section className="composer" aria-label="AI 提问">
      <div className="skill-shortcuts" role="group" aria-label="AI 分析技能">
        {skills.map(({ id, label, shortLabel }) => {
          const Icon = icons[id];
          return (
            <button type="button" key={id} aria-label={label} title={label} aria-pressed={id === skill} onClick={() => onSkill(id === skill ? undefined : id)}>
              <Icon size={15} aria-hidden="true" /><span className="skill-full">{label}</span><span className="skill-short">{shortLabel}</span>
            </button>
          );
        })}
      </div>
      <form className="composer-form" onSubmit={submit}>
        {(selected || topic) && (
          <div className="composer-context">
            {selected && <button type="button" onClick={() => onSkill(undefined)} aria-label={`取消技能：${selected.label}`}><span>{selected.shortLabel}</span><X size={13} /></button>}
            {topic && <button type="button" onClick={onClearTopic} aria-label={`移除关联热点：${topic.title}`}><span>{topic.title}</span><X size={13} /></button>}
          </div>
        )}
        <div className="composer-input-line">
          <textarea
            ref={inputRef}
            id="agent-draft"
            aria-label="输入 AI 问题"
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            placeholder={selected?.placeholder ?? "询问热点或事件…"}
            rows={1}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                event.preventDefault();
                if (!busy && draft.trim()) onSend();
              }
            }}
          />
          <button type="submit" className="send-button" aria-label="发送消息" title="发送消息" disabled={busy || !draft.trim()}><ArrowUp size={17} aria-hidden="true" /></button>
        </div>
      </form>
    </section>
  );
}
