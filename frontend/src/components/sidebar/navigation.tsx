import { AudioLines, CircleDollarSign, Clapperboard, CodeXml, Crosshair, Globe2, LayoutGrid, Network, PanelLeftClose, PanelLeftOpen, Users, X } from "lucide-react";
import type { Ref } from "react";
import { categories } from "@/lib/catalog";
import type { CategoryId } from "@/types/trending";
import { BrandMark } from "@/components/ui/brand";

const categoryIcons = { general: LayoutGrid, tech: Crosshair, entertainment: Clapperboard, community: Users, finance: CircleDollarSign, dev: CodeXml };
export const lensItems = [
  { id: "lens-1", name: "事件透镜 01", icon: Globe2 },
  { id: "lens-2", name: "事件透镜 02", icon: Network },
  { id: "lens-3", name: "事件透镜 03", icon: AudioLines },
] as const;

export type LensId = (typeof lensItems)[number]["id"];

interface NavigationProps {
  category: CategoryId;
  lens?: LensId;
  collapsed: boolean;
  blocked: boolean;
  mobileOpen: boolean;
  closeRef: Ref<HTMLButtonElement>;
  onCategory: (id: CategoryId) => void;
  onLens: (id: LensId) => void;
  onToggle: () => void;
  onClose: () => void;
}

export function Navigation({ category, lens, collapsed, blocked, mobileOpen, closeRef, onCategory, onLens, onToggle, onClose }: NavigationProps) {
  const Collapse = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    <>
      {mobileOpen && <button type="button" className="mobile-nav-scrim" aria-label="关闭导航" tabIndex={-1} onClick={onClose} />}
      <aside id="workspace-nav" className="navigation" inert={blocked} data-mobile-open={mobileOpen} aria-label="工作台导航">
        <div className="nav-brand">
          <div className="nav-brand-logo"><BrandMark /></div>
          <div className="nav-label nav-brand-copy"><strong>EventLens</strong></div>
          <button type="button" className="icon-button nav-toggle" onClick={onToggle} aria-label={collapsed ? "展开导航" : "收起导航"} aria-expanded={!collapsed} aria-controls="workspace-nav">
            <Collapse size={17} aria-hidden="true" />
            <span className="nav-tooltip" aria-hidden="true">{collapsed ? "展开导航" : "收起导航"}</span>
          </button>
          <button type="button" ref={closeRef} className="icon-button nav-mobile-close" aria-label="关闭导航" onClick={onClose}><X size={18} /></button>
        </div>
        <nav className="nav-groups">
          <div className="nav-group">
            <p className="nav-label nav-group-title">热点分区</p>
            {categories.map(({ id, name }) => {
              const Icon = categoryIcons[id];
              return (
                <button type="button" key={id} className="nav-item" aria-label={name} aria-current={!lens && category === id ? "page" : undefined} onClick={() => onCategory(id)}>
                  <Icon size={18} aria-hidden="true" /><span className="nav-label">{name}</span><span className="nav-tooltip" aria-hidden="true">{name}</span>
                </button>
              );
            })}
          </div>
          <div className="nav-group">
            <p className="nav-label nav-group-title">事件透镜</p>
            {lensItems.map(({ id, name, icon: Icon }) => (
              <button type="button" key={id} className="nav-item" aria-label={name} aria-current={lens === id ? "page" : undefined} onClick={() => onLens(id)}>
                <Icon size={18} aria-hidden="true" /><span className="nav-label">{name}</span><span className="nav-tooltip" aria-hidden="true">{name}</span>
              </button>
            ))}
          </div>
        </nav>
      </aside>
    </>
  );
}
