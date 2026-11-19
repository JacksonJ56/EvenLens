import type { OpinionReport } from "@/types/public-opinion";
import styles from "./public-opinion-report.module.css";

export function ReportCoverage({ report }: { report: OpinionReport }) {
  const charts = report.charts ?? [];
  const modules = [{ type: "discussion_topics", label: "主题" }, { type: "emotion_distribution", label: "情绪" }, { type: "stance_comparison", label: "立场" }];
  const notes = Object.entries(report.visualization_notes ?? {});
  return <section className={styles.availability} aria-label="报告分析范围">
    <div className={styles.moduleStates}>{modules.map(module => <span key={module.type} data-ready={charts.some(chart => chart.type === module.type)}>{module.label} · {charts.some(chart => chart.type === module.type) ? "有可核验统计" : "未产生统计"}</span>)}</div>
    {report.status === "partial" && <p>本次研究部分完成，已分析 {report.stats.analyzed_count} / {report.stats.prepared_count} 条保留的一级评论。评论覆盖数量不等于所有分析维度均已完成。</p>}
    {!charts.length && <p>暂无可绘制的可信统计，请查看已完成的文字模块、来源与数据局限。</p>}
    {notes.length > 0 && <details><summary>查看未展示图表的原因（{notes.length} 项）</summary><ul>{notes.map(([key, text]) => <li key={key}>{text}</li>)}</ul></details>}
  </section>;
}
