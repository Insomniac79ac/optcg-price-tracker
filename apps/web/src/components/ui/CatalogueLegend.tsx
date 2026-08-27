"use client";

import { useEffect, useId, useRef, useState } from "react";

import { LEGEND_INTRO, LEGEND_SECTIONS } from "@/lib/terminology";

/** The catalogue's terminology key.
 *
 * WHAT IT HAS TO ACHIEVE, beyond defining words. A collector meeting a print
 * badged Super Rare AND SP Card AND Alt Art has to be able to see that those
 * are three answers to three questions rather than three competing answers to
 * one - otherwise the tile reads as self-contradictory. So the panel opens by
 * saying exactly that, and the terms are grouped under their dimension:
 * Rarity, Special print, Printing. Reading "SP Card" under the heading
 * "Special print" is what stops it being read as a scarcity tier, and no
 * amount of definition text does that job on its own.
 *
 * WHY A DISCLOSURE AND NOT TOOLTIPS. A tooltip is a hover affordance first,
 * and hover does not exist on a phone - where most of this catalogue is read.
 * This is a real <button> controlling a real panel: it works with a mouse, a
 * tap and a keyboard alike, is announced by a screen reader through
 * aria-expanded/aria-controls, and closes on Escape. Individual chips still
 * carry a `title` for the mouse user who hovers one, but that is an
 * enhancement on top of this, never the only route to the words.
 *
 * The panel is rendered in the DOM only while open, so a closed legend adds
 * nothing for assistive technology to walk past. Escape returns focus to the
 * toggle, so a keyboard user is never dropped at the top of the document.
 */
export function CatalogueLegend() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      // Focus goes back where the user left it, not to <body>.
      toggleRef.current?.focus();
    }

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (panelRef.current?.contains(target)) return;
      if (toggleRef.current?.contains(target)) return;
      setOpen(false);
    }

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={toggleRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="inline-flex items-center gap-1.5 rounded-control border border-border-default px-2.5 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60"
      >
        <span aria-hidden="true">?</span>
        What do these labels mean?
      </button>

      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="group"
          aria-label="Catalogue terminology"
          className="absolute left-0 z-20 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-panel border border-border-default bg-bg-elevated p-4 shadow-lg"
        >
          {/* The panel's thesis, before any term: the three vocabularies are
              not in competition. Everything below is an instance of it. */}
          <p className="text-xs leading-relaxed text-text-secondary">{LEGEND_INTRO}</p>

          <div className="mt-3 flex max-h-[60vh] flex-col gap-3.5 overflow-y-auto">
            {LEGEND_SECTIONS.map((section) => (
              <section key={section.id}>
                <h3 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-faint">
                  {section.title}
                </h3>
                {section.blurb && (
                  <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">
                    {section.blurb}
                  </p>
                )}
                {section.terms.length > 0 && (
                  <dl className="mt-1.5 flex flex-col gap-2">
                    {section.terms.map((term) => (
                      <div key={term.key} className="flex flex-col gap-0.5">
                        <dt className="text-xs font-semibold text-text-primary">
                          {term.label}
                          {term.shortLabel && (
                            // The badge form, named beside the full one so a
                            // collector who met "TR" on a tile can find it here.
                            <span className="mono ml-1.5 font-normal text-text-muted">
                              {term.shortLabel}
                            </span>
                          )}
                        </dt>
                        <dd className="text-xs leading-relaxed text-text-secondary">
                          {term.definition}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
