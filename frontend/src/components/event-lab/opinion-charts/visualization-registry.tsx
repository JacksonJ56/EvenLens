"use client";

import { Component, useState, type ComponentType, type ReactNode } from "react";
import dynamic from "next/dynamic";
import type { OpinionChart, OpinionChartPoint, OpinionChartType, OpinionReport } from "@/types/public-opinion";
import type { PlotProps } from "./chart-plots";
import { CommentDrilldown } from "./comment-drilldown";
import styles from "./opinion-charts.module.css";
import { pointColor } from "./palette";
import { ChartAnalysis } from "./chart-analysis";

const loading = () => <div className={styles.skeleton} role="status">正在加载可视化…</div>;
// One chart library, loaded on demand. This registry is the only mapping from wire types to React.
const registry: Record<OpinionChartType, ComponentType<PlotProps>> = {
  emotion_distribution: dynamic(() => import("./chart-plots").then(module => module.EmotionDistributionChart), { ssr: false, loading }),
  discussion_topics: dynamic(() => import("./chart-plots").then(module => module.DiscussionTopicsChart), { ssr: false, loading }),
  stance_comparison: dynamic(() => import("./chart-plots").then(module => module.StanceComparisonChart), { ssr: false, loading }),
  comment_timeline: dynamic(() => import("./chart-plots").then(module => module.CommentTimelineChart), { ssr: false, loading }),
  post_contribution: dynamic(() => import("./chart-plots").then(module => module.PostContributionChart), { ssr: false, loading }),
  discussion_radar: dynamic(() => import("./chart-plots").then(module => module.DiscussionRadarChart), { ssr: false, loading }),
};
class PlotBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p role="alert">图表暂时无法显示，仍可使用下方数据列表。<button type="button" onClick={() => this.setState({ failed: false })}>重试图表</button></p> : this.props.children; }
}
export function OpinionChartCard({ chart, taskId, report }: { chart: OpinionChart; taskId: string; report?: OpinionReport }) {
  const [selectedId, setSelectedId] = useState<string>();
  const [expanded, setExpanded] = useState(false);
  const [presentation, setPresentation] = useState<"radar" | "bar">(() =>
    chart.type === "discussion_radar" && chart.points.filter(point => (point.percent ?? 0) > 0).length < 3 ? "bar" : "radar");
  const Plot = registry[chart.type];
  if (!Plot || !chart.points.length || chart.sample_size <= 0) return null;
  const points = expanded ? chart.points : chart.points.slice(0, 8);
  // Never truncate a time series or a stacked denominator merely to shorten its legend.
  const completePlot = chart.type === "comment_timeline" || chart.type === "stance_comparison";
  const view = completePlot ? chart : { ...chart, points };
  const selected = chart.points.find(point => point.id === selectedId);
  function select(point: OpinionChartPoint) { setSelectedId(current => current === point.id ? undefined : point.id); }
  return <section className={styles.card} data-chart={chart.type} aria-label={chart.title}>
    <header><div><h3>{chart.title}</h3><span>样本 {chart.sample_size} 条{chart.issue && ` · 议题：${chart.issue}`}</span></div><span className={styles.tag}>可追溯统计</span></header>
    <div className={styles.composition} data-chart-layout><div className={styles.figure} data-chart-figure>
    {chart.type === "discussion_radar" && <div className={styles.switcher} role="group" aria-label="样本特征图展示方式">
      <button type="button" aria-pressed={presentation === "radar"} onClick={() => setPresentation("radar")}>雷达图</button>
      <button type="button" aria-pressed={presentation === "bar"} onClick={() => setPresentation("bar")}>柱状图</button>
    </div>}
    <PlotBoundary key={`${chart.type}/${presentation}`}><Plot chart={view} onSelect={select} activeId={selected?.id} presentation={presentation} /></PlotBoundary>
    <p className={styles.caption}>{chart.description}</p>
    {completePlot && chart.points.length > 8 && <p className={styles.caption}>图中已显示全部 {chart.points.length} 项；下方列表可展开查看全部数据及评论。</p>}
    <details className={styles.dataDetails}><summary>查看统计明细与筛选（{chart.points.length} 项）</summary><div className={styles.legend} aria-label={`${chart.title}数据与评论筛选`}>
      {points.map((point, index) => <button type="button" key={point.id} aria-pressed={selected?.id === point.id} onClick={() => select(point)}>
        <i aria-hidden="true" style={{ background: pointColor(chart, point, index) }} />
        <span>{point.label}</span><strong>{point.count} 条{point.percent !== null && <small> {point.percent}%</small>}</strong>
      </button>)}
    </div>
    {chart.points.length > 8 && <button className={styles.expand} type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "收起" : `展开全部 ${chart.points.length} 项`}</button>}
    </details></div><ChartAnalysis chart={chart} report={report} /></div>
    {selected && <CommentDrilldown key={`${taskId}/${chart.id}/${selected.id}`} taskId={taskId} chart={chart} point={selected} onClose={() => setSelectedId(undefined)} />}
  </section>;
}

export function OpinionVisualizations({ charts, taskId, report }: { charts: OpinionChart[]; taskId: string; report?: OpinionReport }) {
  if (!charts.length) return null;
  return <div className={styles.grid}>{charts.map(chart => <OpinionChartCard key={`${taskId}/${chart.id}`} chart={chart} taskId={taskId} report={report} />)}</div>;
}
