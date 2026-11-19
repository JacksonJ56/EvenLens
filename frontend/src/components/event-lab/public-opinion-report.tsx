"use client";

import { ExternalLink } from "lucide-react";
import type { OpinionReport, OpinionSection } from "@/types/public-opinion";
import styles from "./public-opinion-report.module.css";
import { OpinionVisualizations } from "./opinion-charts/visualization-registry";
import { ContextualTimeline } from "./opinion-charts/contextual-timeline";
import { ReportCoverage } from "./report-coverage";
import { OverallAssessmentView } from "./overall-assessment";
import { EvidenceBrowser } from "./evidence-browser";

const sortLabels: Record<string, string> = { hot: "接口热门排序", score: "接口评分排序", time: "时间排序", unknown: "排序未确认" };
const statusLabels = { completed: "已完成", not_applicable: "不适用", insufficient_data: "资料不足", failed: "未完成" };
const evidenceLabels = { verified_fact: "来源事实陈述", supported_inference: "有来源的推断", unverified_hypothesis: "待验证假设", insufficient_evidence: "证据不足" };

function ReportSection({ section, report, sectionIndex }: { section: OpinionSection; report: OpinionReport; sectionIndex: number }) {
  return <section className={styles.section}>
    <header><h3>{section.title}</h3><span className={styles.badge} data-status={section.status}>{statusLabels[section.status]}</span></header>
    <p>{section.summary}</p>
    {section.reason && <p className={styles.muted}>{section.reason}</p>}
    {section.sample_size !== null && <small>统计分母：本次 {section.sample_size} 条有效一级评论；并非全平台用户。</small>}
    <div className={styles.groups}>
      {section.data.map((group, i) => <article className={styles.group} key={`${i}/${group.label}`}>
        <div className={styles.groupHeading}><strong>{group.label}</strong><span>{group.count} 条{group.percent !== null && ` · ${group.percent}%`}</span></div>
        <p>{group.explanation}</p>
        {section.type === "public_emotions" && group.percent !== null && <div className={styles.bar} aria-hidden="true"><i style={{ width: `${Math.min(100, group.percent)}%` }} /></div>}
        {!!group.evidence.length && <EvidenceBrowser taskId={report.task_id} query={`section_index=${sectionIndex}&group_index=${i}`} label={`查看观点证据（${group.evidence.length} 条）`} />}
      </article>)}
    </div>
    {section.contextual_insights.map((insight, i) => <article className={styles.group} key={i}>
      <div className={styles.groupHeading}><strong>{insight.title}</strong><span>{evidenceLabels[insight.classification]}</span></div>
      <p>{insight.explanation}</p>
      {insight.time_range && <p className={styles.meta}>关联时间：{insight.time_range}</p>}
      <p className={styles.muted}>{insight.uncertainty}</p>
      {insight.evidence.map((quote, index) => <blockquote key={index} className={styles.coverage}>{quote.excerpt}</blockquote>)}
      {insight.source_ids.map((id) => {
        const source = report.sources.find((s) => s.id === id);
        return source && <a className={styles.source} key={id} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}<ExternalLink size={12} aria-hidden="true" /></a>;
      })}
    </article>)}
    {!!section.evidence.length && <EvidenceBrowser taskId={report.task_id} query={`section_index=${sectionIndex}`} label="查看本节评论依据" />}
  </section>;
}

export function PublicOpinionReport({ report }: { report: OpinionReport }) {
  const stats = report.stats;
  const charts = report.charts ?? [];
  const firstCharts = ["discussion_topics", "emotion_distribution"].flatMap(type => charts.filter(chart => chart.type === type));
  const stanceCharts = charts.filter(chart => chart.type === "stance_comparison");
  const sampleCharts = ["comment_timeline", "post_contribution", "discussion_radar"].flatMap(type => charts.filter(chart => chart.type === type));
  const chartSections = new Set(charts.flatMap(chart => chart.type === "emotion_distribution" ? ["public_emotions"] : chart.type === "discussion_topics" ? ["discussion_topics"] : chart.type === "stance_comparison" ? ["stance_analysis"] : chart.type === "comment_timeline" ? ["trends"] : []));
  const narrativeSections = report.sections.map((section, index) => ({ section, index })).filter(({ section }) => section.type !== "representative_comments" && !chartSections.has(section.type) && !(section.type === "contextual_insights" && report.context_timeline?.length));
  const representatives = report.sections.map((section, index) => ({ section, index })).filter(({ section }) => section.type === "representative_comments");
  return <div className={styles.report}>
    <h2 className={styles.title}>{report.selected_event.title}</h2>
    <div className={styles.meta}>{report.selection.platform_name}{report.selection.board_name && ` / ${report.selection.board_name}`} · {new Date(report.generated_at).toLocaleString("zh-CN")} · {report.status === "partial" ? "部分完成" : "研究完成"}</div>
    <OverallAssessmentView report={report} />
    <div className={styles.stats} data-report-section="stats">
      {[["有评论 / 相关帖子", `${stats.contributing_post_count ?? stats.post_count} / ${stats.post_count}`], [stats.origin === "imported" ? "导入记录" : "采集记录", stats.origin === "imported" ? stats.input_count : stats.collected_count], ["分析一级评论", stats.analyzed_count], ["上下文回复", stats.reply_count]].map(([label, value]) =>
        <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
    </div>
    <OpinionVisualizations charts={firstCharts} taskId={report.task_id} report={report} />
    <OpinionVisualizations charts={stanceCharts} taskId={report.task_id} report={report} />
    {narrativeSections.map(({ section, index }) => <ReportSection key={`${index}/${section.type}`} section={section} report={report} sectionIndex={index} />)}
    <ContextualTimeline report={report} />
    <OpinionVisualizations charts={sampleCharts} taskId={report.task_id} report={report} />
    {representatives.length > 0 && <section className={styles.representatives} aria-label="代表性评论与证据">
      <h3>代表性评论与证据</h3><p>保留原始顺序的有限参考评论，不代表平台全体用户；按需展开查看。</p>
      {representatives.map(({ section, index }) => <EvidenceBrowser key={index} taskId={report.task_id} query={`section_index=${index}`} label={`浏览参考评论（${section.evidence.length} 条）`} />)}
    </section>}
    <ReportCoverage report={report} />
    <p className={styles.coverage}>本报告仅反映本次采集范围内的前排评论，不代表全平台或全社会。{stats.sort_modes.map((mode) => sortLabels[mode] ?? mode).join(" / ")}。
      {stats.time_start && <> 评论时间：{new Date(stats.time_start).toLocaleDateString("zh-CN")} — {stats.time_end ? new Date(stats.time_end).toLocaleDateString("zh-CN") : "未知"}。</>}
    </p>
    <details className={styles.section}>
      <summary>来源、局限与任务信息</summary>
      <ul>{report.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>
      {report.posts.map((post) => <a className={styles.source} key={post.id} href={post.url} target="_blank" rel="noopener noreferrer">{post.title || post.id}<ExternalLink size={12} aria-hidden="true" /></a>)}
      {report.sources.map((source) => <a className={styles.source} key={source.id} href={source.url} target="_blank" rel="noopener noreferrer">{source.title} · {source.access === "body" ? "已获取正文" : "仅搜索摘要"}<ExternalLink size={12} aria-hidden="true" /></a>)}
      <p className={styles.meta}>任务 {report.task_id} · 模型调用 {report.usage.model_calls ?? 0} 次 · 上游报告 Token {report.usage.reported_tokens ?? 0}</p>
    </details>
  </div>;
}
