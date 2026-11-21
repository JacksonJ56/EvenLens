import { AlertCircle, ArrowUpRight, ChartNoAxesColumnIncreasing, Inbox, MessageSquarePlus, RefreshCw } from "lucide-react";
import { motion } from "motion/react";
import type { BoardView } from "@/hooks/use-board";
import { platforms } from "@/lib/catalog";
import type { Board, BoardQuery, Trend } from "@/types/trending";
import { PlatformIcon } from "./platform-icon";

const timeFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });
const labels = { hot: "热", new: "新", rising: "上升" };

function sourceUrl(value: string) {
  try {
    const url = new URL(value);
    if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) return url.href;
  } catch { /* A missing or invalid source remains readable without navigation. */ }
}

export function Ranking({ query, boards, data, onBoard, onAnalyze }: {
  query: BoardQuery;
  boards: readonly Board[];
  data: BoardView;
  onBoard: (board: string) => void;
  onAnalyze: (trend: Trend) => void;
}) {
  const platform = platforms[query.platform];
  const { state, refreshing, reload } = data;

  return (
    <section className="ranking" aria-label={`${platform.name}榜单`}>
      <div className="ranking-header">
        <div className="ranking-identity"><PlatformIcon id={platform.id} /><h2>{platform.name}</h2></div>
        <div className="board-tabs" aria-label="榜单类型">
          {boards.map(({ id, label }) => (
            <button type="button" key={id} aria-pressed={query.board === id} onClick={() => onBoard(id)}>{label}</button>
          ))}
        </div>
        <button type="button" className="icon-button refresh" aria-label="刷新榜单" title="刷新榜单" disabled={refreshing || state.status === "unavailable"} onClick={reload}><RefreshCw size={16} /></button>
      </div>
      {state.status === "ready" && state.result.mode === "live" && (
        <div className="ranking-status" data-stale={state.result.status === "stale"} role="status">
          <span>{refreshing ? "正在刷新" : state.result.status === "stale" ? "刷新失败，显示上次成功数据" : "已更新"}</span>
          {state.result.updatedAt && <time dateTime={state.result.updatedAt}>{timeFormat.format(new Date(state.result.updatedAt))}</time>}
          {state.result.sourceTitle && <span className="ranking-status-source" title={state.result.sourceTitle}>{state.result.sourceTitle}</span>}
        </div>
      )}
      <div className="ranking-columns row-grid" aria-hidden="true">
        <span>排名</span><span>热点话题</span><span className="source-cell">来源</span><span className="metric-cell"><ChartNoAxesColumnIncreasing size={13} />指标</span><span />
      </div>
      <div className="ranking-content" aria-busy={state.status === "loading"}>
        {state.status === "loading" && (
          <div role="status" aria-label="正在加载榜单">
            {Array.from({ length: 7 }, (_, index) => (
              <div className="ranking-row row-grid skeleton-row" key={index} aria-hidden="true">
                <span /><span /><span className="source-cell" /><span /><i />
              </div>
            ))}
          </div>
        )}
        {state.status === "unavailable" && (
          <div className="board-feedback" role="status"><Inbox size={26} /><strong>该榜单尚未接入</strong><p>可以切换到其他平台或榜单。</p></div>
        )}
        {state.status === "error" && (
          <div className="board-feedback" role="alert"><AlertCircle size={25} /><strong>榜单加载失败</strong><button type="button" className="outline-button" onClick={reload}>重新加载</button></div>
        )}
        {state.status === "ready" && (state.result.items.length ? (
          <motion.ol className="ranking-list" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }}>
            {state.result.items.map((trend) => {
              const href = sourceUrl(trend.url);
              return <li className="ranking-row row-grid" key={trend.id}>
                <span className="rank-number" data-rank={trend.rank}>{String(trend.rank).padStart(2, "0")}</span>
                <div className="trend-topic">
                  {href ? <a className="trend-title-link" href={href} target="_blank" rel="noopener noreferrer" title="在新标签页打开原文">
                    {trend.title}<ArrowUpRight size={12} className="trend-link-icon" aria-hidden="true" />
                  </a> : <span className="trend-title" title="来源链接不可用">{trend.title}</span>}
                  {trend.status && <span className="trend-label" data-status={trend.status}>{labels[trend.status]}</span>}
                </div>
                <span className="source-cell">{platform.name}</span>
                <span className="metric-cell">{trend.metric ? <>{trend.metric.value}<small>{trend.metric.label}</small></> : "—"}</span>
                <button type="button" className="icon-button analyze-button" title="用 AI 分析" aria-label={`用 AI 分析：${trend.title}`} onClick={() => onAnalyze(trend)}><MessageSquarePlus size={15} aria-hidden="true" /></button>
              </li>;
            })}
          </motion.ol>
        ) : <div className="board-feedback" role="status"><Inbox size={26} /><strong>暂无热点</strong><p>可以切换榜单查看其他话题。</p></div>)}
      </div>
    </section>
  );
}
