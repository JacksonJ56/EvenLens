import type { OpinionReport } from "@/types/public-opinion";
import { EvidenceBrowser } from "./evidence-browser";
import styles from "./public-opinion-report.module.css";

export function OverallAssessmentView({ report }: { report: OpinionReport }) {
  const assessment = report.overall_assessment;
  return <section className={styles.assessment} aria-label="AI 总体评价" data-assessment-status={assessment?.status ?? "unavailable"}>
    <div className={styles.assessmentHeading}><h3>AI 总体评价</h3><span>{assessment?.status === "legacy" ? "历史研究摘要" : "基于本次研究与证据"}</span></div>
    {assessment?.summary ? <p className={styles.assessmentText}>{assessment.summary}</p> : <p className={styles.muted}>本次尚未生成有充分依据的综合评价，以下仍可查看实际完成的分析和证据。</p>}
    {assessment?.reason && <p className={styles.assessmentNote}>{assessment.reason}</p>}
    {assessment?.core_judgment && <p className={styles.coreJudgment}><strong>核心判断</strong>{assessment.core_judgment}</p>}
    {!!assessment?.key_findings.length && <ul className={styles.findings} aria-label="关键发现">{assessment.key_findings.map((finding, i) => <li key={i}>{finding}</li>)}</ul>}
    {!!assessment?.evidence.length && <EvidenceBrowser taskId={report.task_id} query="assessment=true" label="查看总体评价的评论依据" />}
    {assessment?.source_ids.map(id => { const source = report.sources.find(source => source.id === id); return source && <a key={id} className={styles.source} href={source.url} target="_blank" rel="noopener noreferrer">参考资料 · {source.title}</a>; })}
  </section>;
}
