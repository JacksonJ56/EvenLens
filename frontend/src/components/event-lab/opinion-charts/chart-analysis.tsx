import type { OpinionChart, OpinionReport } from "@/types/public-opinion";
import { EvidenceBrowser } from "../evidence-browser";
import styles from "./opinion-charts.module.css";

export function ChartAnalysis({ chart, report }: { chart: OpinionChart; report?: OpinionReport }) {
  const interpretation = report?.chart_interpretations?.find(item => item.chart_id === chart.id);
  const index = /^section-(\d+)$/.exec(chart.id)?.[1];
  const section = index !== undefined ? report?.sections[Number(index)] : undefined;
  const groups = section?.data.filter(group => group.explanation).slice(0, 3) ?? [];
  return <div className={styles.analysis} data-chart-analysis>
    <h4>{interpretation ? "AI 解读" : groups.length ? "已有分析归纳" : "如何理解这张图"}</h4>
    {interpretation ? <p>{interpretation.analysis}</p> : groups.length ? <>
      {groups.map((group, i) => <p key={i}><strong>{group.label}</strong> · {group.explanation}</p>)}
      <small>当前保留已有分析；本报告尚未生成独立的图表综合解读。</small>
    </> : <p className={styles.caption}>{chart.description} 本图未产生独立 AI 解读，不能据此追加公众态度或因果判断。</p>}
    {report && <EvidenceBrowser taskId={report.task_id} query={`chart_id=${encodeURIComponent(chart.id)}`} label="查看相关评论证据" />}
    {interpretation?.source_ids.map(id => { const source = report?.sources.find(source => source.id === id); return source && <a key={id} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>; })}
  </div>;
}
