"use client";

import { ChevronRight, FlaskConical, LayoutGrid, Menu, MessageSquare, MoveUpRight } from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChatPanel } from "@/components/agent/chat-panel";
import { Composer } from "@/components/agent/composer";
import { type LensId, lensItems, Navigation } from "@/components/sidebar/navigation";
import { PlatformPicker } from "@/components/trending/platform-picker";
import { Ranking } from "@/components/trending/ranking";
import { useAgent } from "@/hooks/use-agent";
import { categories, platforms } from "@/lib/catalog";
import type { BoardQuery, CategoryId, PlatformId, Trend } from "@/types/trending";

const initialCategory = categories[0];

export function Workspace() {
  const [categoryId, setCategoryId] = useState<CategoryId>(initialCategory.id);
  const [query, setQuery] = useState<BoardQuery>({ platform: initialCategory.platforms[0], board: platforms[initialCategory.platforms[0]].boards[0].id });
  const [lensId, setLensId] = useState<LensId>();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [chatOverlay, setChatOverlay] = useState(false);
  const agent = useAgent(query);
  const input = useRef<HTMLTextAreaElement>(null);
  const chatTrigger = useRef<HTMLButtonElement>(null);
  const chatClose = useRef<HTMLButtonElement>(null);
  const navTrigger = useRef<HTMLButtonElement>(null);
  const navClose = useRef<HTMLButtonElement>(null);
  const composer = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const category = categories.find(({ id }) => id === categoryId) ?? initialCategory;
  const lens = lensItems.find(({ id }) => id === lensId);
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
    setQuery({ platform, board: platforms[platform].boards[0].id });
  }

  function selectCategory(id: CategoryId) {
    const next = categories.find((item) => item.id === id);
    if (!next) return;
    setLensId(undefined);
    if (id !== categoryId) {
      setCategoryId(id);
      selectPlatform(next.platforms[0]);
      setExpanded(false);
    }
    if (mobileNav) closeNav();
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

  return (
    <MotionConfig reducedMotion="user">
      <div className="workspace" data-nav-collapsed={collapsed} onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        if (mobileNav) closeNav();
        else if (agent.open) closeChat();
      }}>
        <Navigation blocked={overlayOpen} category={categoryId} lens={lensId} collapsed={collapsed} mobileOpen={mobileNav} closeRef={navClose}
          onCategory={selectCategory} onLens={(id) => { setLensId(id); if (mobileNav) closeNav(); }}
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
                <LayoutGrid size={16} className="workspace-icon" aria-hidden="true" /><span>{lens ? "事件透镜" : "热点工作台"}</span><ChevronRight size={14} aria-hidden="true" /><strong>{lens?.name ?? category.name}</strong>
              </div>
              <div className="topbar-actions">
                <span className="demo-label"><FlaskConical size={13} aria-hidden="true" />演示数据</span>
                <button type="button" ref={chatTrigger} className="assistant-toggle" aria-expanded={agent.open} aria-controls="agent-panel" onClick={() => agent.open ? closeChat() : openChat()}><MessageSquare size={14} aria-hidden="true" />对话</button>
              </div>
            </header>
            <main className="main-scroll">
              <div className="main-inner">
                {lens ? (
                  <section className="lens-placeholder"><lens.icon size={28} /><h1>{lens.name}</h1><p>这个模块预留给后续事件分析功能。</p><button type="button" className="outline-button" onClick={() => setLensId(undefined)}>返回热点榜单 <MoveUpRight size={14} /></button></section>
                ) : (
                  <>
                    <div key={category.id} className="page-intro">
                      <h1>{category.id === "general" ? "全网热点" : `${category.name}热点`}</h1>
                    </div>
                    <PlatformPicker ids={category.platforms} current={query.platform} expanded={expanded}
                      onExpand={() => setExpanded((value) => !value)}
                      onSelect={(id) => { if (id !== query.platform) selectPlatform(id); }} />
                    <Ranking query={query} onBoard={(board) => setQuery({ ...query, board })} onAnalyze={analyze} />
                  </>
                )}
              </div>
            </main>
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
