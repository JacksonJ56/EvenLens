import { AlertCircle, ArrowUpRight, ChartNoAxesColumnIncreasing, Inbox, MessageSquarePlus, RefreshCw } from "lucide-react";
import { motion } from "motion/react";
import { useBoard } from "@/hooks/use-board";
import { platforms } from "@/lib/catalog";
import type { BoardQuery, Trend } from "@/types/trending";
import { PlatformIcon } from "./platform-icon";

const labels = { hot: "热", new: "新", rising: "上升" };

export function Ranking({ query, onBoard, onAnalyze }: {
  query: BoardQuery;
  onBoard: (board: string) => void;
  onAnalyze: (trend: Trend) => void;
}) {
  const platform = platforms[query.platform];
  const { state, reload } = useBoard(query);

  return (
    <section className="ranking" aria-label={`${platform.name}榜单`}>
      <div className="ranking-header">
        <div className="ranking-identity"><PlatformIcon id={platform.id} /><h2>{platform.name}</h2></div>
        <div className="board-tabs" aria-label="榜单类型">
          {platform.boards.map(({ id, label }) => (
            <button type="button" key={id} aria-pressed={query.board === id} onClick={() => onBoard(id)}>{label}</button>
          ))}
        </div>
        <button type="button" className="icon-button refresh" aria-label="刷新榜单" title="刷新榜单" onClick={reload}><RefreshCw size={16} /></button>
      </div>
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
        {state.status === "error" && (
          <div className="board-feedback" role="alert"><AlertCircle size={25} /><strong>榜单加载失败</strong><button type="button" className="outline-button" onClick={reload}>重新加载</button></div>
        )}
        {state.status === "ready" && (state.result.items.length ? (
          <motion.ol className="ranking-list" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }}>
            {state.result.items.map((trend) => (
              <li className="ranking-row row-grid" key={trend.id}>
                <span className="rank-number" data-rank={trend.rank}>{String(trend.rank).padStart(2, "0")}</span>
                <div className="trend-topic">
                  <a href={trend.url} target="_blank" rel="noopener noreferrer">{trend.title}<ArrowUpRight size={14} className="trend-external" aria-hidden="true" /></a>
                  {trend.status && <span className="trend-label" data-status={trend.status}>{labels[trend.status]}</span>}
                </div>
                <span className="source-cell">{platform.name}</span>
                <span className="metric-cell">{trend.metric ? <>{trend.metric.value}<small>{trend.metric.label}</small></> : "—"}</span>
                <button type="button" className="icon-button analyze-button" title="用 AI 分析" aria-label={`用 AI 分析：${trend.title}`} onClick={() => onAnalyze(trend)}><MessageSquarePlus size={15} aria-hidden="true" /></button>
              </li>
            ))}
          </motion.ol>
        ) : <div className="board-feedback" role="status"><Inbox size={26} /><strong>暂无热点</strong><p>可以切换榜单查看其他话题。</p></div>)}
      </div>
    </section>
  );
}
