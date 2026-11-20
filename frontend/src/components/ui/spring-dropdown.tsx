import { Check, ChevronDown } from "lucide-react";
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from "motion/react";
import { type KeyboardEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import styles from "./spring-dropdown.module.css";

interface Option {
  id: string;
  label: string;
  rank?: number;
  disabled?: boolean;
  reason?: string;
}

interface SpringDropdownProps {
  label: string;
  placeholder: string;
  options: readonly Option[];
  value?: string;
  invalid?: boolean;
  error?: string;
  appearance?: "light";
  onChange: (id: string) => void;
}

// Spring Dropdown interaction adapted from DesignBookmark's motion reference.
const springs = {
  menu: { type: "spring", stiffness: 300, damping: 23 },
  highlight: { type: "spring", stiffness: 620, damping: 36 },
  value: { type: "spring", stiffness: 340, damping: 26 },
} as const;
const instant = { duration: 0 };
type MenuSide = "above" | "below";

function DropdownMenu({ children, reducedMotion, side }: { children: ReactNode; reducedMotion: boolean | null; side: MenuSide }) {
  const present = useIsPresent();
  return (
    <motion.div className={styles.menu} data-side={side} inert={!present}
      initial={{ height: 0, opacity: 0, scaleX: reducedMotion ? 1 : .96 }}
      animate={{ height: "auto", opacity: 1, scaleX: 1 }} exit={{ height: 0, opacity: 0, scaleX: reducedMotion ? 1 : .96 }}
      transition={reducedMotion ? instant : { ...springs.menu, opacity: { duration: .16 } }}>
      {children}
    </motion.div>
  );
}

export function SpringDropdown({ label, placeholder, options, value, invalid, error, appearance, onChange }: SpringDropdownProps) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState<string>();
  const [menuSize, setMenuSize] = useState<{ side: MenuSide; height: number }>({ side: "below", height: 304 });
  const selected = options.find((option) => option.id === value);
  const expanded = open && options.length > 0;
  const activeIndex = options.findIndex((option) => option.id === highlighted);
  const available = options.filter((option) => !option.disabled);

  const measureMenu = useCallback(() => {
    if (!root.current) return;
    const field = root.current.getBoundingClientRect();
    const bounds = root.current.closest("main")?.getBoundingClientRect();
    const below = Math.min(bounds?.bottom ?? window.innerHeight, window.innerHeight) - field.bottom - 10;
    const above = field.top - Math.max(bounds?.top ?? 0, 0) - 10;
    const side = below < 140 && above > below ? "above" : "below";
    const height = Math.max(38, Math.floor(Math.min(304, window.innerHeight * .42, side === "above" ? above : below)));
    setMenuSize((current) => current.side === side && current.height === height ? current : { side, height });
  }, []);

  useEffect(() => {
    if (!expanded) return;
    const boundary = root.current?.closest("main");
    function closeOutside(event: PointerEvent) {
      if (root.current && !event.composedPath().includes(root.current)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    window.addEventListener("resize", measureMenu);
    boundary?.addEventListener("scroll", measureMenu);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      window.removeEventListener("resize", measureMenu);
      boundary?.removeEventListener("scroll", measureMenu);
    };
  }, [expanded, measureMenu]);

  useEffect(() => {
    if (!expanded) return;
    const viewport = list.current;
    const row = viewport?.children[activeIndex] as HTMLElement | undefined;
    if (!viewport || !row) return;
    const top = row.offsetTop;
    const bottom = top + row.offsetHeight;
    if (top < viewport.scrollTop) viewport.scrollTop = top;
    if (bottom > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = bottom - viewport.clientHeight;
  }, [activeIndex, expanded, menuSize.height]);

  function show(last = false) {
    trigger.current?.focus({ preventScroll: true });
    measureMenu();
    setHighlighted(selected && !selected.disabled ? selected.id : available[last ? available.length - 1 : 0]?.id);
    setOpen(true);
  }

  function select(option: Option) {
    if (option.disabled) return;
    setOpen(false);
    if (option.id !== value) onChange(option.id);
  }

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape" && expanded) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      if (expanded) {
        const current = available.findIndex((option) => option.id === highlighted);
        const next = Math.min(Math.max(current + direction, 0), available.length - 1);
        setHighlighted(available[next]?.id);
      } else show(direction < 0);
    } else if (expanded && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      setHighlighted(available[event.key === "Home" ? 0 : available.length - 1]?.id);
    } else if (expanded && (event.key === "Enter" || event.key === " ") && activeIndex >= 0) {
      event.preventDefault();
      select(options[activeIndex]);
    }
  }

  return (
    <div className={styles.field} ref={root} data-open={expanded} data-appearance={appearance}>
      <div className={styles.fieldHeading}>
        <span id={`${id}-label`} className={styles.label}>{label}</span>
        {invalid && <span id={`${id}-error`} className={styles.error}>{error ?? "请选择"}</span>}
      </div>
      <motion.button
        ref={trigger} type="button" role="combobox" className={styles.trigger} disabled={!options.length}
        aria-labelledby={`${id}-label`} aria-expanded={expanded} aria-controls={expanded ? `${id}-options` : undefined}
        aria-invalid={invalid || undefined} aria-describedby={invalid ? `${id}-error` : undefined}
        aria-activedescendant={expanded && activeIndex >= 0 ? `${id}-option-${activeIndex}` : undefined}
        aria-haspopup="listbox" title={selected?.label ?? placeholder}
        onClick={() => { if (expanded) setOpen(false); else show(); }} onKeyDown={keyDown} onBlur={() => setOpen(false)}
        whileTap={reducedMotion ? undefined : { scale: .98 }}
        animate={{ y: expanded && !reducedMotion ? -3 : 0 }} transition={reducedMotion ? instant : springs.menu}
      >
        <span className={styles.dot} data-selected={Boolean(selected)} />
        <span className={styles.value} data-selected={Boolean(selected)}>
          <AnimatePresence initial={false}>
            <motion.span key={selected?.id ?? placeholder} className={styles.slot}
              initial={{ y: reducedMotion ? 0 : 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
              exit={{ y: reducedMotion ? 0 : -14, opacity: 0 }} transition={reducedMotion ? instant : springs.value}>
              {selected?.label ?? placeholder}
            </motion.span>
          </AnimatePresence>
        </span>
        <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={reducedMotion ? instant : springs.value} aria-hidden="true">
          <ChevronDown size={16} />
        </motion.span>
      </motion.button>
      <AnimatePresence initial={false}>
        {expanded && (
          <DropdownMenu reducedMotion={reducedMotion} side={menuSize.side}>
            <div className={styles.list} ref={list} role="listbox" id={`${id}-options`} aria-labelledby={`${id}-label`}
              style={{ maxHeight: menuSize.height }} onMouseDown={(event) => event.preventDefault()}>
              {options.map((option, index) => (
                <motion.div key={option.id} className={styles.option} id={`${id}-option-${index}`} role="option"
                  aria-selected={option.id === value} aria-disabled={option.disabled || undefined} title={option.reason}
                  onPointerMove={() => { if (!option.disabled) setHighlighted(option.id); }} onClick={() => select(option)}
                  initial={{ y: reducedMotion ? 0 : -8, opacity: 0 }} animate={{ y: 0, opacity: option.disabled ? .38 : 1 }}
                  transition={reducedMotion ? instant : { ...springs.value, delay: Math.min(index, 6) * .035 }}>
                  {index === activeIndex && !option.disabled && (
                    <motion.span className={styles.highlight} layoutId={`${id}-highlight`} initial={false}
                      transition={reducedMotion ? instant : springs.highlight} />
                  )}
                  {option.rank === undefined ? <span className={styles.dot} data-selected={option.id === value} /> : <span className={styles.rank}>{String(option.rank).padStart(2, "0")}</span>}
                  <span className={styles.optionLabel}>{option.label}</span>
                  {option.disabled && <small>暂不支持</small>}
                  {option.id === value && <Check size={15} className={styles.check} aria-hidden="true" />}
                </motion.div>
              ))}
            </div>
          </DropdownMenu>
        )}
      </AnimatePresence>
    </div>
  );
}
