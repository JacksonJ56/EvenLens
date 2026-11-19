import { useEffect, useRef, useState } from "react";
import { importOpinionComments } from "@/lib/api/public-opinion";
import type { EventLabEventContext } from "@/types/event-lab";
import styles from "./public-opinion-report.module.css";

export function OpinionImport({ event, onImported }: {
  event?: EventLabEventContext;
  onImported: (id: string, count: number) => void;
}) {
  const [file, setFile] = useState<File>();
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function upload() {
    if (!event || !file || !authorized || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setMessage("");
    try {
      const result = await importOpinionComments(event, file, authorized, abort.signal);
      onImported(result.dataset_id, result.stats.prepared_count);
      setMessage(`已导入 ${result.stats.prepared_count} 条有效一级评论，可点击执行进行真实模型分析。`);
    } catch (error) {
      if (!abort.signal.aborted) setMessage(error instanceof Error ? error.message : "导入失败");
    } finally { if (!abort.signal.aborted) setBusy(false); }
  }

  return <details className={styles.importer}>
    <summary>使用已有授权评论 · JSON / CSV</summary>
    <p>先选择热点。文件中的帖子、评论须属于当前事件和平台，导入数据只用于当前选择。</p>
    <p>JSON 包含 posts、comments 数组；CSV 每行一条评论。字段格式见 <a href="/public-opinion-import.md" target="_blank" rel="noopener noreferrer">导入说明</a>。</p>
    <input type="file" accept=".json,.csv,application/json,text/csv" aria-label="选择授权评论文件"
      disabled={busy} onChange={(e) => { setFile(e.target.files?.[0]); setMessage(""); }} />
    <label className={styles.authorization}><input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />我已获得这些评论的合法使用授权，且已去除不必要的个人信息</label>
    <button type="button" className="outline-button" disabled={!event || !file || !authorized || busy} onClick={() => void upload()}>{busy ? "正在导入…" : "导入评论"}</button>
    {message && <p role="status">{message}</p>}
  </details>;
}
