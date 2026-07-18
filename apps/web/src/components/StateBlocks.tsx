import type { ReactNode } from "react";

/** The loading/error/empty "box" markup repeated near-verbatim across most
 * admin and list pages (system-check, performance, data-retention, logs,
 * collection, wishlist, market opportunities, ...) - centralized here so a
 * page swaps in a component instead of retyping the same className string,
 * not to change how any of them look. */
const BLOCK_BASE = "rounded-lg border p-8 text-center text-sm";

/** Full-width "still loading" block. */
export function LoadingState({ children = "Loading…" }: { children?: ReactNode }) {
  return (
    <div className={`${BLOCK_BASE} border-neutral-800 bg-neutral-900 text-neutral-500`}>
      {children}
    </div>
  );
}

/** Full-width error block. Pass the message as children; for a retry button
 * or other follow-up action, pass `action`. */
export function ErrorState({
  children = "Something went wrong.",
  action,
}: {
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`${BLOCK_BASE} border-rose-900/50 bg-rose-950/30 text-rose-300`}>
      <p>{children}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** "Nothing here" state. `variant="block"` (default) matches the same boxed
 * style as LoadingState/ErrorState - use it for a whole page/section with no
 * results (e.g. "no items match the selected filters"). `variant="inline"`
 * is the lighter plain-text style already used inside dashboard widget
 * cards, for when a full-width box would be too heavy in that context. */
export function EmptyState({
  children,
  variant = "block",
}: {
  children: ReactNode;
  variant?: "block" | "inline";
}) {
  if (variant === "inline") {
    return <p className="text-xs text-neutral-500">{children}</p>;
  }
  return (
    <div className={`${BLOCK_BASE} border-neutral-800 bg-neutral-900 text-neutral-500`}>
      {children}
    </div>
  );
}

/** Inline placeholder for a single missing value in a table cell or stat -
 * not a whole-section empty state (see EmptyState for that). Defaults to
 * the plain "—" already used for a missing number/date; pass a more
 * specific label (e.g. "no price data") when that reads better, optionally
 * italicized to match the existing convention for that style of aside. */
export function MissingValue({
  label = "—",
  italic = false,
}: {
  label?: string;
  italic?: boolean;
}) {
  return <span className={italic ? "italic text-neutral-600" : "text-neutral-600"}>{label}</span>;
}
