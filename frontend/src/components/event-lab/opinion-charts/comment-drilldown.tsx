"use client";

import { X } from "lucide-react";
import type { OpinionChart, OpinionChartPoint } from "@/types/public-opinion";
import { EvidenceBrowser } from "../evidence-browser";
import styles from "./opinion-charts.module.css";

export function CommentDrilldown({ taskId, chart, point, onClose }: { taskId: string; chart: OpinionChart; point: OpinionChartPoint; onClose: () => void }) {
  const query = new URLSearchParams({ chart_id: chart.id, point_id: point.id }).toString();
  return <section className={styles.drilldown} aria-label={`${point.label}的原始评论`}>
    <header><div><strong>{point.label}</strong><span>{point.count} 条 · 本图样本 {chart.sample_size} 条{point.percent !== null && ` · ${point.percent}%`}</span></div><button type="button" aria-label="收起评论" onClick={onClose}><X size={15} /></button></header>
    <p>{point.explanation}</p>
    {point.start_at && <p>{new Date(point.start_at).toLocaleString("zh-CN", { timeZone: chart.timezone ?? "Asia/Shanghai" })} 至 {point.end_at && new Date(point.end_at).toLocaleString("zh-CN", { timeZone: chart.timezone ?? "Asia/Shanghai" })}（不含结束时刻）</p>}
    <EvidenceBrowser taskId={taskId} query={query} label="对应评论 · 点击预览查看全文" initialOpen />
  </section>;
}
