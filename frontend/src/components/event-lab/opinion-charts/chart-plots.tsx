"use client";

import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { OpinionChart, OpinionChartPoint } from "@/types/public-opinion";
import styles from "./opinion-charts.module.css";
import { pointColor } from "./palette";

export interface PlotProps { chart: OpinionChart; onSelect: (point: OpinionChartPoint) => void; activeId?: string; presentation?: "radar" | "bar" }
function HoverDetail({ active, payload, chart }: { active?: boolean; payload?: readonly { payload?: unknown; dataKey?: unknown }[]; chart: OpinionChart }) {
  const raw = payload?.[0]?.payload;
  const id = raw && typeof raw === "object" && "id" in raw ? raw.id : undefined;
  const point = chart.points.find(p => p.id === id || p.id === payload?.[0]?.dataKey);
  if (!active || !point) return null;
  return <div className={styles.tooltip}><strong>{point.label}</strong><span>{point.count} 条{point.percent !== null && ` · ${point.percent}%`}</span><small>本图样本 {chart.sample_size} 条 · 点击查看评论</small></div>;
}
const shorten = (value: string) => value.length > 12 ? value.slice(0, 12) + "…" : value;

export function EmotionDistributionChart({ chart, onSelect, activeId }: PlotProps) {
  return <div className={styles.donut}>
    <ResponsiveContainer width="100%" height={230} minWidth={0}>
      <PieChart accessibilityLayer title="本次评论样本情绪分布">
        <Pie data={chart.points} dataKey="count" nameKey="label" cx="50%" cy="50%" innerRadius={70} outerRadius={96} paddingAngle={2} stroke="var(--color-surface)" isAnimationActive={false}
          onClick={(_, index) => onSelect(chart.points[index])}>
          {chart.points.map((point, i) => <Cell key={point.id} fill={pointColor(chart, point, i)} opacity={!activeId || activeId === point.id ? 1 : .4} cursor="pointer" />)}
        </Pie>
        <Tooltip content={<HoverDetail chart={chart} />} />
      </PieChart>
    </ResponsiveContainer>
    <div className={styles.donutCenter}><strong>{chart.sample_size}</strong><span>实际分类样本</span></div>
  </div>;
}

export function DiscussionTopicsChart({ chart, onSelect, activeId }: PlotProps) {
  const percent = chart.unit === "%";
  return <ResponsiveContainer width="100%" height={Math.max(200, chart.points.length * 37)} minWidth={0}>
    <BarChart accessibilityLayer title={chart.title} data={chart.points} layout="vertical" margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
      <CartesianGrid horizontal={false} stroke="var(--color-line)" strokeDasharray="3 4" />
      <XAxis type="number" allowDecimals={percent} domain={percent ? [0, 100] : [0, "auto"]} tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} unit={percent ? "%" : " 条"} />
      <YAxis type="category" dataKey="label" width={106} tickFormatter={shorten} tick={{ fill: "var(--color-muted)", fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
      <Tooltip cursor={{ fill: "var(--color-hover)" }} content={<HoverDetail chart={chart} />} />
      <Bar dataKey={percent ? "percent" : "count"} name={percent ? "样本占比" : "评论数"} radius={[0, 3, 3, 0]} maxBarSize={16} isAnimationActive={false} onClick={(_, index) => onSelect(chart.points[index])}>
        {chart.points.map((point, i) => <Cell key={point.id} fill={pointColor(chart, point, i)} opacity={!activeId || activeId === point.id ? 1 : .4} cursor="pointer" />)}
      </Bar>
    </BarChart>
  </ResponsiveContainer>;
}
export function StanceComparisonChart({ chart, onSelect, activeId }: PlotProps) {
  const row = Object.fromEntries(chart.points.map(point => [point.id, point.count]));
  return <ResponsiveContainer width="100%" height={150} minWidth={0}>
    <BarChart data={[{ ...row, issue: "本议题" }]} layout="vertical" accessibilityLayer title={chart.issue ?? chart.title} margin={{ top: 12, right: 20, bottom: 5, left: 0 }}>
      <XAxis type="number" allowDecimals={false} domain={[0, chart.sample_size]} unit=" 条" tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
      <YAxis type="category" dataKey="issue" width={48} tick={{ fill: "var(--color-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
      <Tooltip shared={false} cursor={false} content={<HoverDetail chart={chart} />} />
      {chart.points.map((point, i) => <Bar key={point.id} dataKey={point.id} name={point.label} stackId="stance" fill={pointColor(chart, point, i)} opacity={!activeId || activeId === point.id ? 1 : .4} maxBarSize={30} isAnimationActive={false} onClick={() => onSelect(point)} />)}
    </BarChart>
  </ResponsiveContainer>;
}
export const PostContributionChart = DiscussionTopicsChart;

export function DiscussionRadarChart(props: PlotProps) {
  const { chart, onSelect } = props;
  const defined = chart.unit === "%" && chart.normalization === "comment_share" && chart.points.length >= 3 && chart.points.every(point => point.metric_definition && point.percent !== null);
  if (!defined) return null;
  if (props.presentation === "bar") return <DiscussionTopicsChart {...props} />;
  return <ResponsiveContainer width="100%" height={270} minWidth={0}>
    <RadarChart data={chart.points} outerRadius="65%" accessibilityLayer title={chart.title}>
      <PolarGrid stroke="var(--color-line-strong)" />
      <PolarAngleAxis dataKey="label" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
      <PolarRadiusAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: "var(--color-muted)", fontSize: 9 }} tickFormatter={value => `${value}%`} />
      <Radar dataKey="percent" name="样本占比" stroke="var(--color-brand)" fill="var(--color-brand)" fillOpacity={.14} isAnimationActive={false}
        dot={props => <circle cx={props.cx} cy={props.cy} r={4} fill="var(--color-brand)" cursor="pointer" onClick={() => onSelect(chart.points[props.index])} />} />
      <Tooltip content={<HoverDetail chart={chart} />} />
    </RadarChart>
  </ResponsiveContainer>;
}

export function CommentTimelineChart({ chart, onSelect }: PlotProps) {
  // Numeric time spacing preserves gaps. No smoothed curves, synthetic bins or fabricated points.
  const data = chart.points.map(point => ({ ...point, time: Date.parse(point.start_at ?? "") }));
  const label = (time: number) => new Date(time).toLocaleString("zh-CN", { timeZone: chart.timezone ?? "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  return <ResponsiveContainer width="100%" height={240} minWidth={0}>
    <LineChart accessibilityLayer title={chart.title} data={data} margin={{ top: 18, right: 18, left: -22, bottom: 12 }}>
      <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 4" vertical={false} />
      <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} scale="time" tickFormatter={label} minTickGap={42} tick={{ fill: "var(--color-muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
      <YAxis allowDecimals={false} tick={{ fill: "var(--color-muted)", fontSize: 10 }} unit=" 条" axisLine={false} tickLine={false} />
      <Tooltip content={<HoverDetail chart={chart} />} />
      <Line type="linear" dataKey="count" stroke="var(--color-brand)" strokeWidth={2} isAnimationActive={false} dot={{ r: 4, fill: "var(--color-surface)", strokeWidth: 2 }} activeDot={props => <circle cx={props.cx} cy={props.cy} r={6} fill="var(--color-brand)" cursor="pointer" onClick={() => onSelect(chart.points[props.index])} />} />
    </LineChart>
  </ResponsiveContainer>;
}
