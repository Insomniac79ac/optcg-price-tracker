import Link from "next/link";
import type { ReactNode } from "react";

import { RarityBadge } from "@/components/RarityBadge";
import { formatJpy } from "@/lib/format";
import { CardImageFrame } from "./CardImageFrame";
import { PriceCell } from "./PriceCell";
import { accentForVariant } from "./VariantBadge";

export type CardVaultTileDensity = "compact" | "standard" | "showcase";

/** Tile for top holdings / wishlist hits / priority-card lists and the
 * /collection/vault grid (design brief §4) - card image or placeholder,
 * identity, rarity/variant, current price with basis, and an optional
 * status pill (target hit, watching, ...). Rare variants get the same
 * restrained glow as their badge/frame elsewhere - no shine/flash.
 *
 * `density="compact"` (dashboard highlights, pinned-card contexts) keeps
 * the original single-price-line rendering. `"standard"` (the default,
 * used by /collection/vault) and `"showcase"` (larger image) add a second
 * P&L price line, quantity/condition, and a target/grading row - all
 * optional props, so a caller that only has the compact fields still gets
 * a sensible tile. */
export function CardVaultTile({
  cardId,
  cardCode,
  name,
  imageUrl,
  rarity,
  variant,
  setCode,
  valueJpy,
  source,
  priceType,
  mode,
  observedAt,
  statusPill,
  quantity,
  conditionLabel,
  pnlJpy,
  pnlPct,
  targetSellJpy,
  targetHit,
  gradingBadge,
  density = "standard",
}: {
  cardId: number | string;
  cardCode: string;
  name: string;
  imageUrl?: string | null;
  rarity?: string | null;
  variant?: string | null;
  setCode?: string | null;
  valueJpy?: number | null;
  source?: string | null;
  priceType?: string | null;
  mode?: "raw_market" | "graded_adjusted" | null;
  observedAt?: string | null;
  statusPill?: ReactNode;
  quantity?: number | null;
  conditionLabel?: string | null;
  pnlJpy?: number | null;
  pnlPct?: number | null;
  targetSellJpy?: number | null;
  targetHit?: boolean;
  gradingBadge?: ReactNode;
  density?: CardVaultTileDensity;
}) {
  const accent = accentForVariant(variant);
  const showDetail = density !== "compact";

  return (
    <Link
      href={`/cards/${cardId}`}
      className="vault-card flex gap-3 p-2.5 hover:border-text-faint"
    >
      <CardImageFrame
        imageUrl={imageUrl}
        alt={name}
        cardCode={cardCode}
        rarity={rarity}
        setCode={setCode}
        accent={accent}
        size={density === "showcase" ? "md" : "sm"}
      />
      <div className="flex min-w-0 flex-1 flex-col justify-between gap-1">
        <div>
          <div className="flex flex-wrap items-center gap-1">
            <span className="mono text-xs font-medium text-text-primary">{cardCode}</span>
            {rarity && <RarityBadge rarity={rarity} />}
            {showDetail && gradingBadge}
          </div>
          <div className="truncate text-sm text-text-secondary">{name}</div>
          {showDetail && ((quantity !== undefined && quantity !== null) || conditionLabel) && (
            <div className="mono text-[11px] text-text-muted">
              {quantity !== undefined && quantity !== null && `${quantity}×`}
              {quantity !== undefined && quantity !== null && conditionLabel && " · "}
              {conditionLabel ?? ""}
            </div>
          )}
        </div>
        <div className="flex items-end justify-between gap-2">
          <PriceCell
            valueJpy={valueJpy}
            source={source}
            priceType={priceType}
            mode={mode}
            observedAt={observedAt}
            size="sm"
          />
          {statusPill}
        </div>
        {showDetail && pnlJpy !== undefined && (
          <PriceCell valueJpy={pnlJpy} percent={pnlPct} signed size="sm" />
        )}
        {showDetail && targetSellJpy !== undefined && targetSellJpy !== null && (
          <div className="flex items-center gap-1.5 text-[11px] text-text-muted">
            <span className="mono tabular">Target: {formatJpy(targetSellJpy)}</span>
            {targetHit && (
              <span className="badge bg-signal-green/15 text-signal-green ring-1 ring-inset ring-signal-green/30">
                target hit
              </span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}
