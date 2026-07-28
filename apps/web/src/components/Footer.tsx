import { brand } from "@/lib/brand";

/** Site-wide footer - the one place the legal disclaimer lives, so it
 * never needs restating per-page. Deliberately quiet (small, muted text,
 * no decorative treatment) so it reads correctly on both the collector
 * shell and the denser admin screens (brand brief Phase 13 - admin must
 * not inherit decorative flourishes). */
export function Footer() {
  return (
    <footer className="border-t border-border-muted px-4 py-6 text-xs text-text-faint">
      <div className="mx-auto max-w-7xl">
        <p>{brand.legalDisclaimer}</p>
        <p className="mt-1">
          {brand.productName} <span aria-hidden>·</span> {brand.endorsementLine}
        </p>
      </div>
    </footer>
  );
}
