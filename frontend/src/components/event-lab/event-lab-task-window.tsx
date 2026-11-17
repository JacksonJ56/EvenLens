import { AlertCircle, Check, RotateCcw } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import type { EventLabTaskState } from "@/hooks/use-event-lab-task";
import { EventTraceTimeline } from "./event-trace-timeline";
import styles from "./event-lab-workflow.module.css";

export function EventLabTaskWindow({ task, onRetry }: { task: EventLabTaskState; onRetry: () => void }) {
  const reducedMotion = useReducedMotion();
  const body = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  const [height, setHeight] = useState<number>();

  useEffect(() => {
    const element = body.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      if (element.offsetHeight) setHeight(element.offsetHeight);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = panel.current;
    if (!element) return;
    const frame = requestAnimationFrame(() => {
      const boundary = element.closest("main")?.getBoundingClientRect();
      if (boundary && element.getBoundingClientRect().top + 40 > boundary.bottom) {
        element.scrollIntoView({ block: "start", behavior: reducedMotion ? "instant" : "smooth" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [reducedMotion, task.id]);

  return (
    <motion.section ref={panel} id="event-lab-task-window" className={styles.result} aria-labelledby="event-lab-result-heading"
      aria-busy={task.status === "running"}
      initial={reducedMotion ? false : { height: 0, opacity: 0, y: -6 }}
      animate={{ height: height ?? "auto", opacity: 1, y: 0 }}
      transition={{ duration: reducedMotion ? 0 : .28, ease: [.22, .7, .25, 1] }}>
      <div ref={body} className={styles.resultBody}>
        <header className={styles.resultHeader}>
          <h2 id="event-lab-result-heading">{task.feature.mode === "demo" ? "任务演示" : "AI 结果"}</h2>
          <span>{task.feature.name}</span>
          <p>{task.request.event.title}</p>
        </header>
        <div key={task.id} className={styles.resultContent}>
          <AnimatePresence mode="popLayout">
            <motion.div key={task.status} className={styles.resultStage}
              initial={{ opacity: 0, y: reducedMotion ? 0 : 5 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: reducedMotion ? 0 : -4 }}
              transition={{ duration: reducedMotion ? 0 : .18 }}>
              {task.status === "running" && (
                <div className={styles.processing}>
                  <div data-theme="dark" aria-hidden="true"><ThinkingOrb state="solving" size={64} /></div>
                  <strong>{task.feature.mode === "demo" ? "演示任务处理中…" : "AI 正在处理任务…"}</strong>
                </div>
              )}
              {task.status === "complete" && task.result.mode === "demo" && (
                <div className={styles.feedback} data-result="success">
                  <Check aria-hidden="true" size={18} />
                  <div><strong>演示流程已完成</strong><p>此功能尚未接入 AI 分析服务。</p></div>
                </div>
              )}
              {task.status === "complete" && task.result.mode === "live" && (
                <EventTraceTimeline trace={task.result.trace} />
              )}
              {task.status === "error" && (
                <div className={styles.feedback} data-result="error">
                  <AlertCircle aria-hidden="true" size={18} />
                  <div><strong>任务执行失败</strong><p>{task.message}</p></div>
                  <button type="button" className="outline-button" onClick={onRetry}><RotateCcw size={13} aria-hidden="true" />重试</button>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </motion.section>
  );
}
