"use client";

import { windowLabel } from "@/lib/cardPirateIndex";

/** The seven-token timeframe control, rendered from a SERVER window map.
 *
 * ONE CONTROL FOR TWO SURFACES. The aggregate Card Pirate Index and one exact
 * print's analytics publish the same `windows[]` grammar from the same server
 * function, and both have to answer the same hard question the same way: what
 * does a timeframe look like when the data cannot reach it? Two copies of this
 * would be two answers - and the divergence would show up as one surface
 * hiding a short window while the other greys it, for the same underlying
 * fact.
 *
 * AN UNREACHABLE WINDOW STAYS VISIBLE AND STAYS FOCUSABLE. It is not removed,
 * because its absence would silently shrink the grammar the server published;
 * and it never takes the native `disabled` attribute, because that drops the
 * button out of the tab order and takes the explanation with it. Instead the
 * click is refused in the handler, `aria-disabled` states the fact, and the
 * reason travels in the accessible name and the title - so the "why" reaches
 * a keyboard and a screen reader, not just a hovering mouse.
 *
 * `disabled` (the prop) is the whole-control error state, which is different:
 * there is nothing to explain and nothing worth focusing.
 */
export interface WindowTokenRow {
  token: string;
  available: boolean;
  covered_days: number;
  required_days: number | null;
}

export function WindowTokenControl({
  window,
  windows,
  onChange,
  disabled = false,
  shortfallFor,
  label,
  testId,
}: {
  /** The pressed token. The server's echo of what was asked for, not the
   * surface's default - pressing the default would light the wrong button on
   * every subsequent selection. */
  window: string;
  windows: WindowTokenRow[];
  onChange: (window: string) => void;
  disabled?: boolean;
  /** Why this row is unreachable, in a sentence, or null. Supplied by the
   * caller because the two surfaces count different histories ("index
   * history" vs "history for this print") and neither wording is true of the
   * other. */
  shortfallFor: (row: WindowTokenRow) => string | null;
  label: string;
  testId: string;
}) {
  return (
    <div
      // The height is reserved from the first frame. The control is rendered
      // from the SERVER's window list, so it is genuinely empty until the
      // first response lands - and without a floor the heading beside it would
      // jump when the buttons appear.
      className="flex min-h-[22px] items-center gap-0.5 rounded-control border border-border-muted p-0.5"
      role="group"
      aria-label={label}
      data-testid={testId}
    >
      {windows.map((row) => {
        const active = row.token === window;
        const shortfall = shortfallFor(row);
        const unreachable = !row.available;
        const text = windowLabel(row.token);
        return (
          <button
            key={row.token}
            type="button"
            onClick={() => {
              // The guard the absent `disabled` attribute would otherwise
              // provide. An unreachable window must not reach the caller at
              // all: the caller turns a token into a request, and a request
              // for a window the server already said it cannot answer is a
              // round trip whose answer is known before it is sent.
              if (unreachable) return;
              onChange(row.token);
            }}
            aria-pressed={active}
            aria-disabled={unreachable || undefined}
            aria-label={shortfall ? `${text} — ${shortfall}` : undefined}
            title={shortfall ?? undefined}
            disabled={disabled}
            // ONE dimming step, not two. `text-text-muted` is already the
            // second-quietest tier (docs/brand.md "Contrast decisions"), and
            // stacking a 40% opacity on top of it turned six ghost labels
            // beside one solid pill into a control that read as half-broken -
            // the opposite of the honest-about-short-history message intended.
            className={`mono rounded-[4px] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed disabled:opacity-40 sm:px-2 ${
              active ? "bg-bg-card text-text-primary" : "text-text-muted hover:text-text-secondary"
            } ${unreachable ? "cursor-not-allowed opacity-[0.65] hover:text-text-muted" : ""}`}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}
