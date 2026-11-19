"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { opinionAPI } from "@/lib/api/public-opinion";
import type { ChartCommentPage, OpinionComment } from "@/types/public-opinion";
import styles from "./evidence-browser.module.css";

function EvidenceComment({ preview, taskId }: { preview: OpinionComment; taskId: string }) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState<OpinionComment>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open || comment) return;
    const controller = new AbortController();
    setError("");
    const query = new URLSearchParams({ post_id: preview.post_id, comment_id: preview.comment_id });
    void opinionAPI<OpinionComment>(`tasks/${encodeURIComponent(taskId)}/comments?${query}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setComment(value); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "评论读取失败"); });
    return () => controller.abort();
  }, [open, comment, attempt, taskId, preview.post_id, preview.comment_id]);
  return <details className={styles.comment} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><span className={styles.preview}>{preview.content}</span><span className={styles.identifier}>评论 #{preview.comment_id} · 展开原文</span></summary>
    {open && <div className={styles.full}>
      {!comment && !error && <p role="status">正在读取完整原文…</p>}
      {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>}
      {comment && <><blockquote>{comment.content}</blockquote><small>帖子 {comment.post_id} · 评论 {comment.comment_id}<br />
        {comment.source_rank ? `原始顺序 #${comment.source_rank}` : "原始顺序未知"} · {comment.sort_mode === "unknown" ? "排序未确认" : `接口排序：${comment.sort_mode}`}
        {comment.created_at && ` · ${new Date(comment.created_at).toLocaleString("zh-CN")}`}{comment.like_count !== null && ` · ${comment.like_count} 赞`}</small>
        {comment.source_url && <a href={comment.source_url} target="_blank" rel="noopener noreferrer">原始帖子 <ExternalLink size={12} aria-hidden="true" /></a>}</>}
    </div>}
  </details>;
}

export function EvidenceBrowser({ taskId, query, label = "查看相关评论证据", initialOpen = false }: {
  taskId: string; query: string; label?: string; initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);
  const [page, setPage] = useState<ChartCommentPage>();
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setPage(undefined); setError("");
    const endpoint = query.startsWith("chart_id=") && query.includes("point_id=") ? "chart-comments" : "evidence";
    void opinionAPI<ChartCommentPage>(`tasks/${encodeURIComponent(taskId)}/${endpoint}?${query}&offset=${offset}&limit=3&preview=true`, { signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setPage(value); })
      .catch((error: unknown) => { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "评论证据读取失败"); });
    return () => abort.abort();
  }, [taskId, query, open, offset, attempt]);
  return <details className={styles.browser} open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label}{page && <span> · {page.total} 条</span>}</summary>
    {open && <div className={styles.body} aria-live="polite" aria-busy={!page && !error}>
      {!page && !error && <p role="status">正在读取评论预览…</p>}
      {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>}
      {page?.comments.length === 0 && <p>暂无可读取的对应评论。</p>}
      {page?.comments.map(comment => <EvidenceComment key={`${comment.post_id}/${comment.comment_id}`} preview={comment} taskId={taskId} />)}
      {page && <nav aria-label="原始评论分页"><button type="button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 3))}>上一页</button>
        <span>{page.total ? offset + 1 : 0}–{Math.min(offset + page.comments.length, page.total)} / {page.total}</span>
        <button type="button" disabled={offset + 3 >= page.total} onClick={() => setOffset(value => value + 3)}>下一页</button></nav>}
    </div>}
  </details>;
}
