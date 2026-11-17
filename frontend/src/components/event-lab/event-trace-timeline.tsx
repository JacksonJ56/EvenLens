import { ChevronDown, ExternalLink } from "lucide-react";
import type { EventTraceResponse, TraceTimelineEvent } from "@/types/event-trace";
import styles from "./event-trace-timeline.module.css";

const precisionLabel = { datetime: "精确时间", date: "日期", month: "仅知月份", year: "仅知年份", unknown: "时间未知" };
const evidenceLabel = { body: "网页正文", snippet: "搜索片段", summary: "搜索摘要" };

function dateText(event: TraceTimelineEvent) {
  if (!event.occurred_at) return "时间未知";
  return event.time_precision === "datetime" ? event.occurred_at.replace("T", " ").replace("Z", " UTC") : event.occurred_at;
}

function externalUrl(value: string) {
  try {
    const url = new URL(value);
    if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) return url.href;
  } catch {
    return undefined;
  }
}

export function EventTraceTimeline({ trace }: { trace: EventTraceResponse }) {
  const sources = new Map(trace.sources.map((source) => [source.id, source]));
  const suggestedQueries = trace.suggested_queries ?? [];
  return (
    <div className={styles.trace}>
      <div className={styles.header}>
        <h3>{trace.subject ?? "暂未确认事件指向"}</h3>
        <span data-status={trace.status}>{trace.status === "partial" ? "部分结果" : "调查完成"} · 搜索 {trace.search_rounds} 轮</span>
      </div>
      {trace.timeline.length > 0 && (
        <ol className={styles.timeline} aria-label="事件时间线">
          {trace.timeline.map((event) => (
            <li key={event.id}>
              <details className={styles.node}>
                <summary>
                  <div>
                    <span className={styles.date}>
                      {event.occurred_at ? <time dateTime={event.occurred_at}>{dateText(event)}</time> : "时间未知"}
                      {event.occurred_at && <span>{precisionLabel[event.time_precision]}</span>}
                    </span>
                    <strong>{event.title}</strong>
                  </div>
                  <span className={styles.count}>{event.source_ids.length} 个来源</span>
                  <ChevronDown className={styles.chevron} size={15} aria-hidden="true" />
                </summary>
                <div className={styles.nodeBody}>
                  <p>{event.description}</p>
                  {event.uncertainty && <p className={styles.uncertainty}>{event.uncertainty}</p>}
                  <ul aria-label="关联来源">
                    {event.source_ids.map((id) => {
                      const source = sources.get(id);
                      if (!source) return null;
                      const url = externalUrl(source.url);
                      return (
                        <li key={id}>
                          {url ? <a href={url} target="_blank" rel="noopener noreferrer">{source.title} <ExternalLink size={12} aria-hidden="true" /></a> : <strong>{source.title}</strong>}
                          <div className={styles.sourceMeta}>
                            {source.site_name && <span>{source.site_name}</span>}
                            <span>{source.access === "body" ? "已取得正文" : "仅有搜索片段或摘要"}</span>
                            {source.published_at && <span>来源发布 <time dateTime={source.published_at}>{source.published_at}</time></span>}
                          </div>
                          {event.evidence.filter((item) => item.source_id === id).map((item) => (
                            <blockquote key={`${item.kind}-${item.offset}-${item.excerpt}`}>
                              <span>{evidenceLabel[item.kind]}</span>
                              <p>{item.excerpt}</p>
                            </blockquote>
                          ))}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </details>
            </li>
          ))}
        </ol>
      )}
      {trace.missing_aspects.length > 0 && (
        <div className={styles.notes}>
          <strong>资料缺口</strong>
          <ul>{trace.missing_aspects.map((note) => <li key={note}>{note}</li>)}</ul>
        </div>
      )}
      {suggestedQueries.length > 0 && (
        <details className={styles.warnings}>
          <summary>可补充的检索词</summary>
          <ul>{suggestedQueries.map((query) => <li key={query}>{query}</li>)}</ul>
        </details>
      )}
      {trace.warnings.length > 0 && (
        <details className={styles.warnings}>
          <summary>调查提示（{trace.warnings.length}）</summary>
          <ul>{trace.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
