import { brand } from "@/lib/brand";

import { AtlasMark, type AtlasMarkTone } from "./AtlasMark";

/** Full horizontal lockup - mark + "CardPirate Atlas" + "by CardPirateTCG"
 * endorsement line. Use wherever there's room for the complete identity:
 * sign-in page, footer, OG image, documentation. */
export function AtlasLogo({
  tone = "onDark",
  className = "",
}: {
  tone?: AtlasMarkTone;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <AtlasMark tone={tone} title={null} aria-hidden className="h-8 w-6 shrink-0" />
      <span className="flex flex-col leading-tight">
        <span className="font-display text-base font-semibold tracking-tight text-text-primary">
          {brand.productName}
        </span>
        <span className="text-[10px] font-medium uppercase tracking-wider text-text-faint">
          {brand.endorsementLine}
        </span>
      </span>
    </span>
  );
}

/** Compact mark for tight chrome (topbar, mobile nav, favicon-adjacent
 * contexts) - icon plus the short name only, with the full product name
 * kept for assistive tech via a visually-hidden span. */
export function AtlasCompactMark({
  tone = "onDark",
  className = "",
  showShortName = true,
  "aria-hidden": ariaHidden,
}: {
  tone?: AtlasMarkTone;
  className?: string;
  showShortName?: boolean;
  /** Pass when an ancestor already supplies the accessible name (e.g. a
   * <Link> with its own aria-label) - suppresses the sr-only "CardPirate
   * Atlas" span so it doesn't concatenate onto the ancestor's name instead
   * of being redundant-but-harmless inside it. */
  "aria-hidden"?: boolean;
}) {
  return (
    <span aria-hidden={ariaHidden} className={`inline-flex shrink-0 items-center gap-1.5 ${className}`}>
      <AtlasMark tone={tone} title={null} aria-hidden className="h-6 w-[18px] shrink-0" />
      {!ariaHidden && <span className="sr-only">{brand.productName}</span>}
      {showShortName && (
        <span aria-hidden className="font-display text-sm font-semibold tracking-tight text-text-primary">
          {brand.shortName}
        </span>
      )}
    </span>
  );
}
