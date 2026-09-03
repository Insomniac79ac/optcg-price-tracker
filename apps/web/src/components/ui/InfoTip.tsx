"use client";

import { useEffect, useId, useRef, useState } from "react";

/** A small "what does this mean?" explainer attached to a label.
 *
 * A DISCLOSURE, NOT A HOVER TOOLTIP. The trigger is a real `<button>` and the
 * explanation opens on click, on Enter and on Space, because those are the
 * same event. That is the whole reason this is not `title=""` or a
 * CSS `:hover` panel:
 *
 *   - a phone has no hover, and most collectors browse Atlas on one;
 *   - a keyboard user reaches a `<button>` with Tab and opens it with Enter,
 *     which no hover-only affordance allows;
 *   - a screen reader announces the button, its expanded state, and then the
 *     explanation, because `aria-expanded` and `aria-controls` tie them
 *     together and the panel is real DOM rather than a native `title` string
 *     that assistive technology may or may not read.
 *
 * Escape closes it and returns focus to the trigger; a click anywhere outside
 * closes it too. Both are the behaviours a reader already expects from every
 * other popover they have used, and getting them wrong traps focus in a 40px
 * question mark.
 *
 * DELIBERATELY NOT A MODAL. It explains a word beside a price; it does not
 * take over the page, does not trap focus and does not dim anything behind
 * it. Content is a plain sentence passed in as `text` - this component
 * renders no markup of its own from it and no caller may pass elements, so
 * there is nowhere for a link or a control to end up nested inside the
 * button's own accessible name.
 *
 * NEVER PUT ONE INSIDE A LINK. A button inside an anchor is invalid HTML and
 * behaves unpredictably on both keyboard and touch, which is exactly why the
 * catalogue tile - a single large `<Link>` - renders evidence labels as plain
 * text and leaves the explanations to the print detail page, where the label
 * is not inside a link.
 */
export function InfoTip({
  label,
  text,
  className = "",
}: {
  /** What the button is FOR, for assistive technology - e.g. "About Current
   * listing". Never rendered visually; the glyph is the visual affordance. */
  label: string;
  /** The one plain sentence to show. Text only, by design - see above. */
  text: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const containerRef = useRef<HTMLSpanElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      // Focus must come back to the trigger, or a keyboard user closing the
      // panel is dropped at the top of the document.
      buttonRef.current?.focus();
    }

    function onPointerDown(event: MouseEvent | TouchEvent) {
      const target = event.target;
      if (target instanceof Node && containerRef.current?.contains(target)) return;
      setOpen(false);
    }

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  return (
    <span ref={containerRef} className={`relative inline-flex ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
        // 20px of hit area around a 12px glyph: the minimum that is reliably
        // tappable beside 11px text without the glyph itself growing loud
        // enough to compete with the price above it.
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border-muted text-[10px] font-semibold leading-none text-text-muted transition-colors hover:border-accent-teal/50 hover:text-text-secondary focus:outline-none focus-visible:border-accent-teal focus-visible:ring-2 focus-visible:ring-accent-teal/60"
      >
        <span aria-hidden="true">?</span>
      </button>
      {/* Always in the DOM would mean always announced; rendered only when
          open, the panel is announced when the reader asks for it and the
          button's aria-expanded says it is there to ask for. */}
      {open && (
        <span
          id={panelId}
          role="note"
          className="absolute bottom-full left-0 z-20 mb-1.5 w-60 max-w-[75vw] rounded-panel border border-border-muted bg-bg-elevated px-3 py-2 text-[11px] font-normal normal-case leading-snug tracking-normal text-text-secondary shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}
