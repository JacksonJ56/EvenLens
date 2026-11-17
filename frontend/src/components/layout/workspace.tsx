"use client";

import { ChevronRight, Database, FlaskConical, LayoutGrid, Menu, MessageSquare } from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChatPanel } from "@/components/agent/chat-panel";
import { Composer } from "@/components/agent/composer";
import { EventLabPanel } from "@/components/event-lab/event-lab-panel";
import { Navigation } from "@/components/sidebar/navigation";
import { PlatformPicker } from "@/components/trending/platform-picker";
import { Ranking } from "@/components/trending/ranking";
import { TrendPreview, type TrendPreviewSelection } from "@/components/trending/trend-preview";
import { trendingMode } from "@/lib/api/trending";
import { useAgent } from "@/hooks/use-agent";
import { useBoard } from "@/hooks/use-board";
import { categories } from "@/lib/catalog";
import { resolveEventLabSource } from "@/lib/event-lab";
import type { EventLabSelection } from "@/types/event-lab";
import type { BoardQuery, CategoryId, CategoryPlatform, PlatformId, Trend } from "@/types/trending";

const initialCategory = categories[0];

function defaultBoard(platform: CategoryPlatform): BoardQuery {
  return { platform: platform.id, board: platform.boards[0].id };
}

export function Workspace() {
  const [categoryId, setCategoryId] = useState<CategoryId>(initialCategory.id);
  const [query, setQuery] = useState<BoardQuery>(() => defaultBoard(initialCategory.platforms[0]));
  const [labOpen, setLabOpen] = useState(false);
  const [labSelection, setLabSelection] = useState<EventLabSelection>();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [preview, setPreview] = useState<TrendPreviewSelection>();
  const previewReturnFocus = useRef<HTMLButtonElement>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [chatOverlay, setChatOverlay] = useState(false);
  const agent = useAgent(query);
  const input = useRef<HTMLTextAreaElement>(null);
  const chatTrigger = useRef<HTMLButtonElement>(null);
  const chatClose = useRef<HTMLButtonElement>(null);
  const navTrigger = useRef<HTMLButtonElement>(null);
  const navClose = useRef<HTMLButtonElement>(null);
  const boardHeading = useRef<HTMLHeadingElement>(null);
  const composer = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const category = categories.find(({ id }) => id === categoryId) ?? initialCategory;
  const activePlatform = category.platforms.find(({ id }) => id === query.platform) ?? category.platforms[0];
  const labSource = labSelection ? resolveEventLabSource(labSelection) : undefined;
  const labQuery = trendingMode === "live" ? labSource?.query : undefined;
  const boardData = useBoard(labOpen ? labQuery : query);
  const overlayOpen = chatOverlay && agent.open;

  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const overlay = matchMedia("(max-width: 1050px)");
    const mobile = matchMedia("(max-width: 640px)");
    const syncPreference = () => setReducedMotion(preference.matches);
    const syncOverlay = () => setChatOverlay(overlay.matches);
    const closeDesktopNav = () => { if (!mobile.matches) setMobileNav(false); };
    syncPreference();
    syncOverlay();
    preference.addEventListener("change", syncPreference);
    overlay.addEventListener("change", syncOverlay);
    mobile.addEventListener("change", closeDesktopNav);
    return () => {
      preference.removeEventListener("change", syncPreference);
      overlay.removeEventListener("change", syncOverlay);
      mobile.removeEventListener("change", closeDesktopNav);
    };
  }, []);

  useLayoutEffect(() => {
    const element = composer.current;
    const container = stage.current;
    if (!element || !container) return;
    const resize = () => container.style.setProperty("--composer-height", `${element.offsetHeight}px`);
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    return () => observer.disconnect();
  }, []);

  function selectPlatform(platform: PlatformId) {
    const selected = category.platforms.find(({ id }) => id === platform);
    if (selected) {
      setPreview(undefined);
      setQuery(defaultBoard(selected));
    }
  }

  function selectCategory(id: CategoryId) {
    const next = categories.find((item) => item.id === id);
    if (!next) return;
    setLabOpen(false);
    if (id !== categoryId) {
      setPreview(undefined);
      setCategoryId(id);
      setQuery(defaultBoard(next.platforms[0]));
      setExpanded(false);
    }
    if (mobileNav) closeNav();
  }

  function toggleLab() {
    setPreview(undefined);
    if (!labOpen) setLabSelection((selection) => selection ?? { categoryId, platformId: query.platform, boardId: query.board });
    setLabOpen((open) => !open);
    if (mobileNav) closeNav();
  }

  function returnToBoards() {
    setLabOpen(false);
    requestAnimationFrame(() => boardHeading.current?.focus({ preventScroll: true }));
  }

  function closeChat() {
    agent.setOpen(false);
    requestAnimationFrame(() => chatTrigger.current?.focus());
  }

  function openNav() {
    setMobileNav(true);
    requestAnimationFrame(() => navClose.current?.focus());
  }

  function closeNav() {
    setMobileNav(false);
    requestAnimationFrame(() => navTrigger.current?.focus());
  }

  function openChat() {
    agent.setOpen(true);
    requestAnimationFrame(() => chatClose.current?.focus());
  }

  function analyze(trend: Trend) {
    agent.setTopic(trend);
    input.current?.focus({ preventScroll: true });
  }

  function closePreview() {
    previewReturnFocus.current = preview?.trigger ?? null;
    setPreview(undefined);
  }

  useLayoutEffect(() => {
    if (preview) return;
    previewReturnFocus.current?.focus({ preventScroll: true });
    previewReturnFocus.current = null;
  }, [preview]);

  return (
    <MotionConfig reducedMotion="user">
      <div className="workspace" data-nav-collapsed={collapsed} onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        if (mobileNav) closeNav();
        else if (agent.open) closeChat();
      }}>
        <Navigation blocked={overlayOpen} category={categoryId} labOpen={labOpen} collapsed={collapsed} mobileOpen={mobileNav} closeRef={navClose}
          onCategory={selectCategory} onLabToggle={toggleLab}
          onToggle={() => setCollapsed((value) => !value)} onClose={closeNav} />
        <motion.div
          ref={stage}
          className="stage"
          inert={mobileNav}
          data-chat-open={agent.open}
          initial={false}
          animate={{ "--chat-progress": agent.open ? 1 : 0 }}
          transition={{ duration: reducedMotion ? 0 : 0.3, ease: [0.25, 0.8, 0.25, 1] }}
        >
          <div className="main-panel" inert={overlayOpen}>
            <header className="topbar">
              <div className="breadcrumbs">
                <button type="button" ref={navTrigger} className="icon-button mobile-nav-toggle" aria-label="打开导航" aria-expanded={mobileNav} aria-controls="workspace-nav" onClick={openNav}><Menu size={20} /></button>
                <LayoutGrid size={16} className="workspace-icon" aria-hidden="true" /><span>{labOpen ? "工作台" : "热点工作台"}</span><ChevronRight size={14} aria-hidden="true" /><strong>{labOpen ? "事件实验室" : category.name}</strong>
              </div>
              <div className="topbar-actions">
                {!labOpen && <span className="demo-label">{trendingMode === "mock" ? <><FlaskConical size={13} aria-hidden="true" />演示数据</> : <><Database size={13} aria-hidden="true" />真实数据</>}</span>}
                <button type="button" ref={chatTrigger} className="assistant-toggle" aria-expanded={agent.open} aria-controls="agent-panel" onClick={() => agent.open ? closeChat() : openChat()}><MessageSquare size={14} aria-hidden="true" />对话</button>
              </div>
            </header>
            <main className="main-scroll" hidden={labOpen} data-preview-open={Boolean(preview)} inert={Boolean(preview)}>
              <div className="main-inner">
                <div key={category.id} className="page-intro">
                  <h1 ref={boardHeading} tabIndex={-1}>{category.id === "general" ? "全网热点" : `${category.name}热点`}</h1>
                </div>
                <PlatformPicker ids={category.platforms.map(({ id }) => id)} current={query.platform} expanded={expanded}
                  onExpand={() => setExpanded((value) => !value)}
                  onSelect={(id) => { if (id !== query.platform) selectPlatform(id); }} />
                <Ranking query={query} boards={activePlatform.boards} data={boardData.forQuery(query)} onBoard={(board) => { setPreview(undefined); setQuery({ ...query, board }); }} onAnalyze={analyze} onPreview={setPreview} previewId={preview?.trend.id} />
              </div>
            </main>
            <main id="event-lab-panel" className="main-scroll" hidden={!labOpen}>
              <div className="main-inner">
                {labSelection && labSource && (
                  <EventLabPanel active={labOpen} selection={labSelection} source={labSource}
                    data={labQuery ? boardData.forQuery(labQuery) : undefined} onChange={setLabSelection} onReturn={returnToBoards} />
                )}
              </div>
            </main>
            {preview && <TrendPreview selection={preview} onClose={closePreview} />}
          </div>
          <button type="button" className="chat-scrim" tabIndex={-1} aria-label="关闭 AI 侧栏" aria-hidden={!agent.open} onClick={closeChat} />
          <ChatPanel open={agent.open} messages={agent.messages} closeRef={chatClose} onClose={closeChat} />
          <div className="composer-position" ref={composer}>
            <Composer draft={agent.draft} skill={agent.skill} topic={agent.topic} busy={agent.busy} inputRef={input}
              onDraft={agent.setDraft} onSkill={agent.setSkill} onClearTopic={() => agent.setTopic(undefined)} onSend={() => { input.current?.focus({ preventScroll: true }); void agent.send(); }} />
          </div>
        </motion.div>
      </div>
    </MotionConfig>
  );
}
