import styles from "./event-lab-orb.module.css";

export function EventLabOrb({ active, size = "compact" }: { active: boolean; size?: "compact" | "panel" }) {
  return <span className={styles.orb} data-active={active} data-size={size} aria-hidden="true" />;
}
