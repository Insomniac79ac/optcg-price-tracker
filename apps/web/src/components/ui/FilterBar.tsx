import type { ReactNode } from "react";

/** Thin wrapper formalizing the filters-row markup already used on every
 * filterable page - not a new pattern, just a shared className bundle. */
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="mb-4 flex flex-wrap items-center gap-2">{children}</div>;
}

export const FILTER_INPUT_CLASS =
  "rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-faint";

export const FILTER_LABEL_CLASS = "flex items-center gap-1.5 text-xs text-text-secondary";
