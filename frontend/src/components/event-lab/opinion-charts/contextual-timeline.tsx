"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";
import type { OpinionReport } from "@/types/public-opinion";
import styles from "./opinion-charts.module.css";
const levels: Record<string, string> = { verified_fact: "来源事实陈述", supported_inference: "有证据的推断", unverified_hypothesis: "待核实假设", insufficient_evidence: "证据不足" };

export function ContextualTimeline({ report }: { report: OpinionReport }) {
  const [selected, setSelected] = useState<string>();
  if (!report.context_timeline?.length) return null;
  return <section className={styles.card}>
    <header><div><h3>热点背后的关联</h3><span>背景时间线与证据 · 时间相近不代表存在因果</span></div></header>
    <ol className={styles.timeline}>
      {report.context_timeline.map(node => <li key={node.id}>
        <button type="button" aria-expanded={selected === node.id} onClick={() => setSelected(current => current === node.id ? undefined : node.id)}>
          <span>{node.occurred_at ? (/^\d{4}-\d{2}-\d{2}$/.test(node.occurred_at) ? node.occurred_at : new Date(node.occurred_at).toLocaleString("zh-CN")) : "时间未确定"} · {node.time_label}</span>
          <strong>{node.title}</strong>{node.classification && <small>{levels[node.classification] ?? "证据状态未知"}</small>}
        </button>
        {selected === node.id && <div className={styles.contextDetail}>
          <p>{node.description}</p>{node.uncertainty && <p className={styles.caption}>{node.uncertainty}</p>}
          {node.evidence.map((quote, i) => <blockquote key={i}>{quote.excerpt}</blockquote>)}
          {node.source_ids.map(id => { const source = report.sources.find(source => source.id === id); return source && <a key={id} href={source.url} target="_blank" rel="noopener noreferrer">{source.title} · {source.access === "body" ? "已获取正文" : "仅摘要"} <ExternalLink size={12} /></a>; })}
          {node.post_id && report.posts.filter(post => post.id === node.post_id).map(post => <a key={post.id} href={post.url} target="_blank" rel="noopener noreferrer">原始帖子 <ExternalLink size={12} /></a>)}
          {node.kind === "capture" && report.selected_event.url && <a href={report.selected_event.url} target="_blank" rel="noopener noreferrer">热点原始链接 <ExternalLink size={12} /></a>}
        </div>}
      </li>)}
    </ol>
  </section>;
}
