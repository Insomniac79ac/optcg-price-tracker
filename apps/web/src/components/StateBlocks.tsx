import type { ReactNode } from "react";

import { SkeletonRows } from "@/components/ui/SkeletonBlock";

/** The loading/error/empty "box" markup repeated near-verbatim across most
 * admin and list pages (system-check, performance, data-retention, logs,
 * collection, wishlist, market opportunities, ...) - centralized here so a
 * page swaps in a component instead of retyping the same className string,
 * not to change how any of them look. */
const BLOCK_BASE = "rounded-panel border p-8 text-center text-sm";

/** Full-width "still loading" block - a quiet skeleton shimmer plus the
 * caption text (kept, not decorative-only, since several pages' tests
 * assert on the exact loading caption, e.g. "Loading dashboard…"). */
export function LoadingState({ children = "Loading…" }: { children?: ReactNode }) {
  return (
    <div className={`${BLOCK_BASE} border-border-default bg-bg-surface text-text-muted`}>
      <div className="mx-auto mb-3 max-w-xs">
        <SkeletonRows rows={2} />
      </div>
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
    <div className={`${BLOCK_BASE} border-signal-red/40 bg-signal-red/10 text-signal-red`}>
      <p>{children}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** "Nothing here" state. `variant="block"` (default) matches the same boxed
 * style as LoadingState/ErrorState - use it for a whole page/section with no
 * results (e.g. "no items match the selected filters"). `variant="inline"`
 * is the lighter plain-text style already used inside dashboard widget
 * cards, for when a full-width box would be too heavy in that context.
 * Deliberately plain/quiet ("vault, empty" not a bright SaaS illustration
 * or anime art - see docs "do not do" list). */
export function EmptyState({
  children,
  variant = "block",
}: {
  children: ReactNode;
  variant?: "block" | "inline";
}) {
  if (variant === "inline") {
    return <p className="text-xs text-text-muted">{children}</p>;
  }
  return (
    <div className={`${BLOCK_BASE} border-border-default bg-bg-surface text-text-muted`}>
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
  return <span className={italic ? "italic text-text-faint" : "text-text-faint"}>{label}</span>;
}
