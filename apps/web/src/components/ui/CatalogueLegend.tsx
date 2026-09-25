"use client";

import { useState } from "react";
import { LEGEND_INTRO, LEGEND_SECTIONS } from "@/lib/terminology";
import { CatalogueDialog } from "./CatalogueDialog";

export function CatalogueLegend() {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open} className="min-h-11 rounded-control px-2 text-xs text-text-secondary underline focus-visible:outline-2 focus-visible:outline-accent-teal">What do these labels mean?</button>
    {open && <CatalogueDialog label="Catalogue terminology" onClose={() => setOpen(false)}>
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
    </CatalogueDialog>}
  </>;
}
