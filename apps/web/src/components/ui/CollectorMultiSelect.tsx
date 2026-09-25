"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, useCallback } from "react";
import { toggleFilter } from "@/lib/catalogueState";
import styles from "./CollectorMultiSelect.module.css";

/** Native popover puts options above artwork and inside a modal sheet's top
 * layer. Checkboxes retain normal Tab/Space semantics and never act like a
 * single-select menu. The fallback stays usable in older browsers. */
export function CollectorMultiSelect({ label, options, selected, onChange, optionLabel = (value) => value }: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
  optionLabel?: (value: string) => string;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const values = [...new Set([...options, ...selected])];
  const searchable = values.length > 8;
  const visible = values.filter((value) => `${value} ${optionLabel(value)}`.toLowerCase().includes(search.toLowerCase()));
  const close = useCallback(() => {
    setOpen(false);
    trigger.current?.focus({ preventScroll: true });
  }, []);

  useLayoutEffect(() => {
    if (!open || !panel.current || !trigger.current) return;
    const element = panel.current;
    const position = () => {
      const rect = trigger.current!.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const width = Math.min(320, window.innerWidth - 32);
      const below = viewportHeight - rect.bottom - 16;
      const above = rect.top - 16;
      const upwards = below < 300 && above > below;
      Object.assign(element.style, {
        width: `${width}px`,
        left: `${Math.max(16, Math.min(rect.left, window.innerWidth - width - 16))}px`,
        top: upwards ? "auto" : `${rect.bottom + 6}px`,
        bottom: upwards ? `${viewportHeight - rect.top + 6}px` : "auto",
        maxHeight: `${Math.max(100, Math.min(420, upwards ? above : below))}px`,
      });
    };
    position();
    if (typeof element.showPopover === "function") element.showPopover();
    else { element.removeAttribute("popover"); element.dataset.fallback = "true"; }
    (element.querySelector<HTMLElement>('input[type="search"]') ?? element.querySelector<HTMLElement>('input[type="checkbox"]') ?? element.querySelector<HTMLElement>('button:not(:disabled)'))?.focus({ preventScroll: true });
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      if (typeof element.hidePopover === "function" && element.matches(":popover-open")) element.hidePopover();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) close();
    };
    const keyboard = (event: KeyboardEvent) => {
      // Escape dismisses options first, leaving the mobile draft sheet open.
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    };
    const focus = (event: FocusEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keyboard, true);
    document.addEventListener("focusin", focus);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keyboard, true);
      document.removeEventListener("focusin", focus);
    };
  }, [open, close]);

  return <div ref={root} className={styles.field}>
    <button ref={trigger} type="button" className={styles.trigger} aria-label={`${label} ${selected.length ? `${selected.length} selected` : "Any"}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => { if (open) close(); else { setSearch(""); setOpen(true); } }}
      onKeyDown={(event) => { if (event.key === "ArrowDown") { event.preventDefault(); setSearch(""); setOpen(true); } }}>
      <span>{label}</span>
      <span className={styles.summary}>{selected.length ? `${selected.length} selected` : "Any"}</span>
      <span aria-hidden="true">⌄</span>
    </button>
    {open && <div ref={panel} id={id} role="dialog" aria-label={`${label} options`} popover="auto" className={styles.panel}
      onToggle={(event) => { if (event.newState === "closed") setOpen(false); }}>
      <div className={styles.panelHeading}>
        <span>{label}</span>
        <button type="button" disabled={!selected.length} onClick={() => onChange([])} aria-label={`Clear ${label.toLowerCase()}`}>Clear</button>
      </div>
      {searchable && <input type="search" className={styles.search} aria-label={`Search ${label.toLowerCase()} options`} placeholder="Find an option…" value={search} onChange={(event) => setSearch(event.target.value)} />}
      <div className={styles.options} role="group" aria-label={label}>
        {visible.map((value) => <label key={value} className={styles.option}>
          <input type="checkbox" checked={selected.includes(value)} onChange={() => onChange(toggleFilter(selected, value))} />
          <span>{optionLabel(value)}</span>
        </label>)}
        {!visible.length && <p className={styles.empty}>No matching options</p>}
      </div>
      <button type="button" className={styles.done} onClick={close}>Done</button>
    </div>}
  </div>;
}
