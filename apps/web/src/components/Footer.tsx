import { brand } from "@/lib/brand";

/** Site-wide footer - the one place the legal disclaimer lives, so it
 * never needs restating per-page. Deliberately quiet (small text, no
 * decorative treatment, no invented links or social accounts) so it reads
 * correctly on both the collector shell and the denser admin screens (brand
 * brief Phase 13 - admin must not inherit decorative flourishes).
 *
 * Quiet is not the same as unreadable. The disclaimer used to sit at
 * `--text-faint` (#6b6656 on #171717, ~3.1:1), which is below the 4.5:1 bar
 * docs/brand.md sets for body text and is the one thing on the page that has
 * to be legible for legal rather than design reasons - it is now
 * `--text-muted` (~4.7:1), still the quietest tier that actually passes.
 * The lockup line keeps the product name one step brighter so
 * "CardPirate Atlas / by CardPirateTCG" reads as the brand rather than as
 * more small print, and stacks on mobile where the two halves would
 * otherwise wrap mid-lockup. */
export function Footer() {
  return (
    <footer className="mt-16 border-t border-border-muted px-4 py-7 text-xs">
      <div className="mx-auto flex max-w-7xl flex-col gap-2.5">
        <p className="max-w-3xl leading-relaxed text-text-muted">{brand.legalDisclaimer}</p>
        <p className="flex flex-wrap items-baseline gap-x-1.5 text-text-muted">
          <span className="font-medium text-text-secondary">{brand.productName}</span>
          <span aria-hidden className="text-text-faint">
            ·
          </span>
          <span>{brand.endorsementLine}</span>
        </p>
      </div>
    </footer>
  );
}
