import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { Artifact } from "@/types/agent";
import type { EventTraceResponse } from "@/types/event-trace";
import type { OpinionReport } from "@/types/public-opinion";
import { EventTraceTimeline } from "../event-lab/event-trace-timeline";
import { PublicOpinionReport } from "../event-lab/public-opinion-report";

interface Result {
  artifact: Artifact;
  result: EventTraceResponse | OpinionReport | null;
  progress: { stage: string; message: string; at: string }[];
}
export function CopilotResult({
  artifact,
  threadId,
  onClose,
}: {
  artifact: Artifact;
  threadId: string;
  onClose: () => void;
}) {
  const [value, setValue] = useState<Result>(),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0),
    [cancelling, setCancelling] = useState(false);
  const url = `/api/copilot/results/${artifact.id}?thread_id=${encodeURIComponent(threadId)}`;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setValue(undefined);
    setError("");
    async function read() {
      try {
        const r = await fetch(url, {
            signal: controller.signal,
            cache: "no-store",
          }),
          d = await r.json();
        if (!r.ok) throw new Error(d.detail ?? "无法读取结果");
        setValue(d);
        setError("");
        if (!d.result && ["running", "queued"].includes(d.artifact.status))
          timer = setTimeout(() => void read(), 1600);
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "读取失败");
      }
    }
    void read();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [url, attempt]);
  async function cancel() {
    setCancelling(true);
    try {
      const r = await fetch(url, { method: "DELETE" }),
        d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      setAttempt((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消未完成");
    } finally {
      setCancelling(false);
    }
  }
  return (
    <section className="copilot-result" aria-label="Copilot 分析结果">
      <header>
        <button type="button" className="outline-button" onClick={onClose}>
          <ArrowLeft size={14} />
          返回热榜
        </button>
        <h1>{artifact.title}</h1>
        <p>{artifact.kind === "trace" ? "事件溯源" : "公众舆情分析"}</p>
      </header>
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            className="outline-button"
            onClick={() => setAttempt((n) => n + 1)}
          >
            重新读取
          </button>
        </p>
      )}
      {!value && !error && <p role="status">正在读取分析状态…</p>}
      {value && !value.result && (
        <div role="status">
          <p>{value.artifact.message}</p>
          {value.progress.length > 0 && (
            <ol>
              {value.progress.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ol>
          )}
          {["running", "queued"].includes(value.artifact.status) && (
            <button
              className="outline-button"
              disabled={cancelling}
              onClick={() => void cancel()}
            >
              取消后台任务
            </button>
          )}
          {["failed", "interrupted", "cancelled"].includes(
            value.artifact.status,
          ) && <p>可在对话中明确要求重新分析；已有完成结果会保留。</p>}
        </div>
      )}
      {value?.result &&
        (artifact.kind === "trace" ? (
          <EventTraceTimeline trace={value.result as EventTraceResponse} />
        ) : (
          <PublicOpinionReport report={value.result as OpinionReport} />
        ))}
    </section>
  );
}
