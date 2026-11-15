import { ChevronDown } from "lucide-react";
import type { CSSProperties } from "react";
import { platforms } from "@/lib/catalog";
import type { PlatformId } from "@/types/trending";
import { PlatformIcon } from "./platform-icon";

interface PlatformPickerProps {
  ids: readonly PlatformId[];
  current: PlatformId;
  expanded: boolean;
  onExpand: () => void;
  onSelect: (id: PlatformId) => void;
}

export function PlatformPicker({ ids, current, expanded, onExpand, onSelect }: PlatformPickerProps) {
  const rowCounts = {
    "--platform-rows-wide": Math.ceil(ids.length / 6),
    "--platform-rows-medium": Math.ceil(ids.length / 4),
    "--platform-rows-narrow": Math.ceil(ids.length / 3),
  } as CSSProperties;

  function option(id: PlatformId, className = "platform-option", hidden = false) {
    return (
      <button type="button" key={id} className={className} title={platforms[id].name}
        aria-pressed={id === current} aria-hidden={hidden || undefined} tabIndex={hidden ? -1 : undefined}
        onClick={() => onSelect(id)}>
        <PlatformIcon id={id} /><span>{platforms[id].name}</span>
      </button>
    );
  }

  return (
    <section className="platform-section" aria-label="热点平台">
      <div className="section-line">
        <h2>热点平台 <span className="section-count">{ids.length}</span></h2>
        <button type="button" className="text-button" aria-expanded={expanded} aria-controls="platform-options" onClick={onExpand}>
          {expanded ? "收起平台" : "全部平台"}<ChevronDown size={15} className={expanded ? "rotate-180" : ""} />
        </button>
      </div>
      <div className="platform-options" id="platform-options" data-expanded={expanded} style={rowCounts}>
        <div className="platform-grid">{ids.map((id) => option(id))}</div>
        {ids.indexOf(current) >= 3 && (
          option(current, "platform-option platform-current", expanded)
        )}
      </div>
    </section>
  );
}
