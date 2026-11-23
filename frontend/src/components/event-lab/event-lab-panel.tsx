import { ArrowLeft, Clock3, ExternalLink, Play, RefreshCw, X } from "lucide-react";
import { type Dispatch, type FormEvent, type SetStateAction, useEffect, useState } from "react";
import { SpringDropdown } from "@/components/ui/spring-dropdown";
import type { BoardView } from "@/hooks/use-board";
import { useEventLabTask } from "@/hooks/use-event-lab-task";
import { trendingMode } from "@/lib/api/trending";
import { categories, platforms } from "@/lib/catalog";
import { eventLabFeatures } from "@/lib/event-lab-features";
import type { resolveEventLabSource } from "@/lib/event-lab";
import type { EventLabEventContext, EventLabSelection } from "@/types/event-lab";
import { EventLabOrb } from "./event-lab-orb";
import { EventLabTaskWindow } from "./event-lab-task-window";
import styles from "./event-lab-panel.module.css";
import { getOpinionCapabilities } from "@/lib/api/public-opinion";
import type { OpinionCapabilities } from "@/types/public-opinion";
import { OpinionImport } from "./opinion-import";
import { usePlatformSession } from "@/hooks/use-platform-session";
import { PlatformSessionNotice } from "./platform-session-notice";

interface EventLabPanelProps {
  active: boolean;
  selection: EventLabSelection;
  source: ReturnType<typeof resolveEventLabSource>;
  data?: BoardView;
  onChange: Dispatch<SetStateAction<EventLabSelection | undefined>>;
  onReturn: () => void;
}

export function EventLabPanel({ active, selection, source, data, onChange, onReturn }: EventLabPanelProps) {
  const [featureId, setFeatureId] = useState<string>();
  const [submitted, setSubmitted] = useState(false);
  const [capabilities, setCapabilities] = useState<OpinionCapabilities>();
  const [capabilityError, setCapabilityError] = useState("");
  const [capabilityAttempt, setCapabilityAttempt] = useState(0);
  const [imported, setImported] = useState<{ key: string; id: string; count: number }>();
  const { task, run, cancel } = useEventLabTask();
  const { category, platform, board, query } = source;
  const feature = eventLabFeatures.find(({ id }) => id === featureId);
  const busy = task?.status === "running";
  const opinion = feature?.id === "public_opinion";
  const platformCapability = platform ? capabilities?.platforms[platform.id] : undefined;
  const unsupported = Boolean(opinion && platform && capabilities && !platformCapability?.supported);
  const platformError = unsupported ? "当前平台暂不支持公众舆情分析，请重新选择支持的平台。" : undefined;
  const state = data?.state;
  const result = state?.status === "ready" && state.result.mode === "live" ? state.result : undefined;
  const trends = result?.items ?? [];
  const trend = trends.find(({ id }) => id === selection.trendId);
  const explicitBoard = platform && platform.boards.length > 1 ? board : undefined;
  const context: EventLabEventContext | undefined = category && query && trend ? {
    categoryId: category.id, categoryName: category.name,
    platformId: query.platform, platformName: platforms[query.platform].name,
    feedId: query.board, boardId: explicitBoard?.id, boardName: explicitBoard?.label,
    capturedAt: result?.updatedAt, trendId: trend.id, title: trend.title, url: trend.url || undefined, trend,
  } : undefined;
  const contextKey = context ? `${context.categoryId}/${context.platformId}/${context.feedId}/${context.trendId}` : "";
  const dataset = imported?.key === contextKey ? imported : undefined;
  const session = usePlatformSession(platform?.id, Boolean(opinion && platformCapability?.supported));
  const sessionBlocked = Boolean(opinion && platform && !dataset && !session.ready);
  const matchesTask = !task || (active && context?.trendId === task.request.event.trendId &&
    context?.platformId === task.request.event.platformId && context?.feedId === task.request.event.feedId &&
    context?.categoryId === task.request.event.categoryId && featureId === task.feature.id);

  useEffect(() => {
    if (!opinion) return;
    const controller = new AbortController();
    getOpinionCapabilities(controller.signal).then((value) => { setCapabilities(value); setCapabilityError(""); })
      .catch(() => { if (!controller.signal.aborted) setCapabilityError("平台能力配置读取失败，请检查后端后重试"); });
    return () => controller.abort();
  }, [opinion, capabilityAttempt]);

  useEffect(() => {
    if (!active || !result || !selection.trendId || trend) return;
    onChange((current) => current === selection ? { ...current, trendId: undefined } : current);
  }, [active, onChange, result, selection, trend]);

  useEffect(() => {
    if (!matchesTask) cancel();
  }, [matchesTask, cancel]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (context && feature && !unsupported && (!opinion || (capabilities && (dataset || session.ready)))) {
      setSubmitted(false);
      void run(feature, { event: context, featureId: feature.id, datasetId: opinion ? dataset?.id : undefined });
    } else {
      setSubmitted(true);
      const form = event.currentTarget;
      requestAnimationFrame(() => form.querySelector<HTMLButtonElement>('[aria-invalid="true"]:not(:disabled)')?.focus());
    }
  }

  function clearSelections() {
    cancel();
    onChange({});
    setFeatureId(undefined);
    setSubmitted(false);
    setImported(undefined);
  }

  let status: string | undefined;
  if (board) {
    if (trendingMode === "mock") status = "演示模式下暂无真实热点";
    else if (state?.status === "loading" || data?.refreshing) status = "正在加载热点…";
    else if (state?.status === "error") status = "热点加载失败，请重试";
    else if (state?.status === "unavailable") status = "该榜单尚未接入";
    else if (result?.status === "stale") status = "刷新失败，显示上次成功获取的热点";
    else if (result && !trends.length) status = "该榜单暂无热点";
  }

  return (
    <section className={`event-lab-panel ${styles.panel}`} aria-labelledby="event-lab-heading">
      <header className={styles.header}>
        <div className={styles.heading}>
          <div className="event-lab-mark"><EventLabOrb active={active} size="panel" /></div>
          <h1 id="event-lab-heading">事件实验室</h1>
        </div>
        <button type="button" className="outline-button" onClick={onReturn}>
          <ArrowLeft size={14} aria-hidden="true" />返回热点榜单
        </button>
      </header>
      <form className={styles.selection} aria-labelledby="event-lab-selection-heading" onSubmit={submit}>
        <h2 id="event-lab-selection-heading">实验选择</h2>
        <div className={styles.sources}>
          <SpringDropdown label="热点分区" placeholder="选择分区" value={category?.id} invalid={submitted && !category}
            options={categories.map(({ id, name }) => ({ id, label: name }))}
            onChange={(id) => {
              const next = categories.find((item) => item.id === id);
              if (next) {
                cancel();
                onChange({ categoryId: next.id });
              }
            }} />
          <SpringDropdown key={category?.id} label="热点平台" placeholder="选择平台" value={platform?.id}
            invalid={unsupported || (submitted && !platform)} error={platformError}
            options={category?.platforms.map(({ id }) => ({ id, label: platforms[id].name,
              disabled: opinion && !capabilities?.platforms[id]?.supported,
              reason: opinion && !capabilities?.platforms[id]?.supported ? "当前功能暂不支持该平台" : undefined })) ?? []}
            onChange={(id) => {
              const next = category?.platforms.find((item) => item.id === id);
              if (next && (!opinion || capabilities?.platforms[id]?.supported)) {
                cancel();
                onChange({ categoryId: selection.categoryId, platformId: next.id });
              }
            }} />
          {platform && platform.boards.length > 1 && (
            <SpringDropdown key={`${category?.id}/${platform.id}`} label="榜单选择" placeholder="选择榜单" value={board?.id} invalid={submitted && !board}
              options={platform.boards} onChange={(boardId) => {
                cancel();
                onChange({ categoryId: selection.categoryId, platformId: platform.id, boardId });
              }} />
          )}
        </div>
        <div className={styles.targets}>
          <SpringDropdown key={`${category?.id}/${platform?.id}/${board?.id}`} label="热点事件" placeholder="选择热点"
            options={trends.map(({ id, title, rank }) => ({ id, label: title, rank }))} value={context?.trendId}
            invalid={submitted && !context} onChange={(trendId) => {
              cancel();
              onChange({ ...selection, trendId });
            }} />
          <SpringDropdown label="实验功能" placeholder="选择实验功能" appearance="light"
            options={eventLabFeatures.map(({ id, name }) => ({ id, label: name }))} value={feature?.id}
            invalid={submitted && !feature} onChange={(id) => {
              cancel();
              setFeatureId(id);
            }} />
        </div>
        {opinion && <div className={styles.opinionStatus}>
          {capabilityError ? <span role="alert">{capabilityError} <button type="button" className="outline-button"
            onClick={() => setCapabilityAttempt((value) => value + 1)}>重新读取</button></span> : !capabilities ? <span role="status">正在读取平台能力…</span> : null}
          {!unsupported && platform && platformCapability?.supported && <PlatformSessionNotice name={platforms[platform.id].name} session={session} />}
          {capabilities && category && !category.platforms.some(({ id }) => capabilities.platforms[id]?.supported) &&
            <p>当前分区暂无支持公众舆情分析的平台，请选择其他分区。</p>}
          {dataset && <p role="status">已绑定当前热点的 {dataset.count} 条一级评论。</p>}
          {!dataset && sessionBlocked && <p>在线采集需先验证该平台登录会话；也可以导入授权评论后执行。</p>}
          {!unsupported && <OpinionImport key={contextKey} event={context} onImported={(id, count) => {
            cancel(); setImported({ key: contextKey, id, count });
          }} />}
        </div>}
        <div className={styles.footer}>
          <div className={styles.details}>
            {status && <span role="status">{status}</span>}
            {context?.url && <a className={styles.original} href={context.url} target="_blank" rel="noopener noreferrer">查看原文 <ExternalLink size={12} aria-hidden="true" /></a>}
          </div>
          <div className={styles.actions}>
            <button type="button" className="outline-button"
              disabled={!data || data.refreshing || state?.status === "loading" || state?.status === "unavailable"} onClick={data?.reload}>
              <RefreshCw size={13} aria-hidden="true" />刷新热点
            </button>
            <button type="button" className="outline-button" onClick={clearSelections}>
              <X size={14} aria-hidden="true" />清空选项
            </button>
            <button type="submit" className={styles.execute} disabled={busy || unsupported || sessionBlocked || (opinion && !capabilities)} aria-controls={task ? "event-lab-task-window" : undefined}>
              {busy ? <Clock3 size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
              {busy ? "执行中…" : "执行"}
            </button>
          </div>
        </div>
      </form>
      <span className="sr-only" role="status">
        {task?.status === "running" && "AI 正在处理任务"}
        {task?.status === "complete" && "分析已完成"}
        {task?.status === "error" && "任务执行失败，可重试"}
      </span>
      {task && matchesTask && <EventLabTaskWindow task={task} onCancel={cancel} onRetry={() => {
        void run(task.feature, { ...task.request, resumeTaskId: task.progress?.id });
      }} />}
    </section>
  );
}
