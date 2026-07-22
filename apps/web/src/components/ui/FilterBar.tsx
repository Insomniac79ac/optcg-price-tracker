"use client";

import { Children, useState, type ReactNode } from "react";

/** Below this many filter controls, collapsing adds friction without saving
 * meaningful space, so everything just wraps (mobile flex-wrap already keeps
 * it from overflowing horizontally). */
const MOBILE_ALWAYS_VISIBLE = 3;

/** Thin wrapper formalizing the filters-row markup already used on every
 * filterable page. Desktop/tablet: every filter stays inline and wraps
 * (flex-wrap), never causing page-level horizontal overflow. Mobile: once a
 * page passes more than a few filters, the rest collapse behind a "More
 * filters" toggle so the primary row stays short - the saved-view/quick-
 * action rows below it aren't pushed down by a wall of selects. */
export function FilterBar({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const items = Children.toArray(children).filter(Boolean);
  const overflowCount = items.length - MOBILE_ALWAYS_VISIBLE;
  const canCollapse = overflowCount > 0;

  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-2">
        {items.map((child, i) => (
          <div
            key={i}
            className={canCollapse && !expanded && i >= MOBILE_ALWAYS_VISIBLE ? "hidden sm:block" : ""}
          >
            {child}
          </div>
        ))}
      </div>
      {canCollapse && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1.5 text-[11px] font-medium text-text-muted hover:text-text-secondary sm:hidden"
        >
          {expanded ? "Fewer filters ▾" : `More filters (${overflowCount}) ▸`}
        </button>
      )}
    </div>
  );
}

export const FILTER_INPUT_CLASS =
  "rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-faint";

export const FILTER_LABEL_CLASS = "flex items-center gap-1.5 text-xs text-text-secondary";
