import { RarityBadge } from "@/components/RarityBadge";
import { VariantBadge } from "./VariantBadge";

/** The card_code/name/rarity/variant/language identity cluster the design
 * brief §4 wants prioritized on card detail pages - extracted from the
 * pattern already used inline in cards/[id] and the duplicate-cards cell. */
export function CardIdentityBlock({
  cardCode,
  name,
  nameSecondary,
  rarity,
  variant,
  language,
  setCode,
  asHeading = false,
}: {
  cardCode: string;
  name: string;
  nameSecondary?: string | null;
  rarity?: string | null;
  variant?: string | null;
  language?: string | null;
  setCode?: string | null;
  /** Card detail pages are the one place this identity cluster IS the page
   * title - everywhere else (tiles, table cells) it's just a label. */
  asHeading?: boolean;
}) {
  const NameTag = asHeading ? "h1" : "div";
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mono text-sm font-medium text-text-primary">{cardCode}</span>
        {rarity && <RarityBadge rarity={rarity} />}
        <VariantBadge variant={variant} />
      </div>
      <NameTag
        className={
          asHeading
            ? "mt-0.5 text-xl font-semibold text-text-primary"
            : "mt-0.5 text-sm text-text-secondary"
        }
      >
        {name}
      </NameTag>
      {nameSecondary && <div className="text-xs text-text-muted">{nameSecondary}</div>}
      {(setCode || language) && (
        <div className="mt-0.5 text-[11px] text-text-muted">
          {[setCode, language?.toUpperCase()].filter(Boolean).join(" · ")}
        </div>
      )}
    </div>
  );
}
