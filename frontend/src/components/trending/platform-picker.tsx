import { ChevronDown } from "lucide-react";
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
  return (
    <section className="platform-section" aria-label="热点平台">
      <div className="section-line">
        <h2>热点平台 <span className="section-count">{ids.length}</span></h2>
        {ids.length > 3 && (
          <button type="button" className="text-button" aria-expanded={expanded} aria-controls="platform-options" onClick={onExpand}>
            {expanded ? "收起平台" : "全部平台"}<ChevronDown size={15} className={expanded ? "rotate-180" : ""} />
          </button>
        )}
      </div>
      <div className="platform-options" id="platform-options" data-expanded={expanded}>
        <div className="platform-clip">
          <div className="platform-grid">
            {ids.map((id) => (
              <button type="button" key={id} className="platform-option" aria-pressed={id === current} onClick={() => onSelect(id)}>
                <PlatformIcon id={id} /><span>{platforms[id].name}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
