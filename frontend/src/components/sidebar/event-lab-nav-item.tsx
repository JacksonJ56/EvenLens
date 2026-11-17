import { EventLabOrb } from "@/components/event-lab/event-lab-orb";
import styles from "./event-lab-nav-item.module.css";

export function EventLabNavItem({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button type="button" className={`nav-item ${styles.item}`} aria-label="事件实验室"
      aria-current={active ? "page" : undefined} aria-controls="event-lab-panel" onClick={onToggle}>
      <span className={styles.wash} aria-hidden="true" />
      <EventLabOrb active={active} />
      <span className={`nav-label ${styles.label}`}>事件实验室</span>
      <span className="nav-tooltip" aria-hidden="true">事件实验室</span>
    </button>
  );
}
