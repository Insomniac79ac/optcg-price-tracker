"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** The browser's modal top layer stays above transformed artwork and sticky
 * navigation. Native dialog supplies focus containment and background inertness. */
export function CatalogueDialog({ label, children, onClose, sheet = false }: {
  label: string; children: ReactNode; onClose: () => void; sheet?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog ref={ref} aria-label={label} aria-modal="true"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      className={`fixed m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-0 text-text-primary shadow-2xl backdrop:bg-black/70 ${sheet ? "mb-4" : ""}`}>
      <div className="min-w-0 p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="font-display text-xl font-semibold">{label}</h2>
          <button type="button" onClick={onClose} aria-label={`Close ${label.toLowerCase()}`} className="min-h-11 min-w-11 rounded-control border border-border-default focus-visible:outline-2 focus-visible:outline-accent-teal">×</button>
        </div>
        {children}
      </div>
    </dialog>, document.body,
  );
}
