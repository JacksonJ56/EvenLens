import { ArrowUpRight, X } from "lucide-react";
import { useAnimate, useReducedMotion } from "motion/react";
import { type CSSProperties, useId, useLayoutEffect, useRef } from "react";
import { platforms } from "@/lib/catalog";
import type { Trend } from "@/types/trending";
import { PlatformIcon } from "./platform-icon";
import { TrendPreviewContent } from "./trend-preview-content";

export interface TrendPreviewSelection {
  trend: Trend;
  row: HTMLLIElement;
  trigger: HTMLButtonElement;
}

const ease = [0.22, 0.72, 0.25, 1] as const;
function rowGeometry(panel: HTMLElement, row: HTMLLIElement) {
  const bounds = panel.getBoundingClientRect();
  const source = row.getBoundingClientRect();
  const left = Math.max(0, Math.min(source.left - bounds.left, bounds.width - 1));
  const top = Math.max(0, Math.min(source.top - bounds.top, bounds.height - 1));
  return {
    "--preview-top": top,
    "--preview-right": Math.max(0, Math.min(bounds.right - source.right, bounds.width - left - 1)),
    "--preview-bottom": Math.max(0, Math.min(bounds.bottom - source.bottom, bounds.height - top - 1)),
    "--preview-left": left,
  };
}

function getPreviewUrl(value: string) {
  try {
    const url = new URL(value);
    if ((url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password) return url;
  } catch {
    // Invalid URLs have no external navigation target.
  }
}

export function TrendPreview({ selection, onClose }: { selection: TrendPreviewSelection; onClose: () => void }) {
  const { trend, row } = selection;
  const [scope, animate] = useAnimate<HTMLElement>();
  const reducedMotion = useReducedMotion();
  const animation = useRef<ReturnType<typeof animate> | null>(null);
  const mounted = useRef(false);
  const closing = useRef(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const heading = useId();
  const url = getPreviewUrl(trend.url);
  const theme = trend.preview?.themeColor;
  const themeStyle = theme && /^#[\da-f]{6}$/i.test(theme) ? { "--preview-accent": theme } as CSSProperties : undefined;

  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useLayoutEffect(() => {
    const panel = scope.current;
    closeButton.current?.focus({ preventScroll: true });
    if (!panel || reducedMotion) return;
    const source = rowGeometry(panel, row);
    animation.current = animate(panel, {
      "--preview-top": [source["--preview-top"], 0],
      "--preview-right": [source["--preview-right"], 0],
      "--preview-bottom": [source["--preview-bottom"], 0],
      "--preview-left": [source["--preview-left"], 0],
      "--preview-blend": [0, 1],
    }, { duration: 0.32, ease });
    return () => animation.current?.stop();
  }, [animate, reducedMotion, row, scope]);

  async function close() {
    const panel = scope.current;
    if (closing.current) return;
    closing.current = true;
    if (!panel || reducedMotion) {
      onClose();
      return;
    }

    await animate(".trend-preview-toolbar, .trend-preview-body", { opacity: 0 }, { duration: 0.1, ease: "easeOut" });
    if (!mounted.current) return;
    animation.current?.stop();
    // The inset surface reaches the row's bounds and styling before it is removed.
    animation.current = animate(panel, {
      ...rowGeometry(panel, row),
      "--preview-blend": 0,
    }, { duration: 0.29, ease });
    await animation.current;
    if (!mounted.current) return;
    await animate(panel, { opacity: 0 }, { duration: 0.05 });
    if (mounted.current) onClose();
  }

  return (
    <section ref={scope} data-platform={trend.platform} data-row-divider={!row.matches(":last-child")} style={themeStyle} className="trend-preview"
      role="dialog" aria-labelledby={heading} onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        void close();
      }}>
      <header className="trend-preview-toolbar">
        <PlatformIcon id={trend.platform} />
        <div className="trend-preview-heading">
          <h2 id={heading} title={trend.title}>{trend.title}</h2>
          <span>{platforms[trend.platform].name}</span>
        </div>
        {url && <a className="outline-button trend-preview-external" href={url.href} target="_blank" rel="noopener noreferrer" aria-label="在浏览器中打开" title="在浏览器中打开"><ArrowUpRight size={15} /><span>在浏览器中打开</span></a>}
        <button ref={closeButton} type="button" className="icon-button" aria-label="关闭网页预览" title="关闭网页预览" onClick={() => void close()}><X size={18} /></button>
      </header>
      <div className="trend-preview-body">
        <TrendPreviewContent trend={trend} hasSource={Boolean(url)} />
      </div>
    </section>
  );
}
