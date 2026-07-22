import Link from "next/link";
import type { ReactNode } from "react";

import { RarityBadge } from "@/components/RarityBadge";
import { CardImageFrame } from "./CardImageFrame";
import { PriceCell } from "./PriceCell";
import { accentForVariant } from "./VariantBadge";

/** Compact tile for top holdings / wishlist hits / priority-card lists
 * (design brief §4) - card image or placeholder, identity, rarity/variant,
 * current price with basis, and an optional status pill (target hit,
 * watching, ...). Rare variants get the same restrained glow as their
 * badge/frame elsewhere - no shine/flash. */
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
}) {
  const accent = accentForVariant(variant);

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
        size="sm"
      />
      <div className="flex min-w-0 flex-1 flex-col justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-1">
            <span className="mono text-xs font-medium text-text-primary">{cardCode}</span>
            {rarity && <RarityBadge rarity={rarity} />}
          </div>
          <div className="truncate text-sm text-text-secondary">{name}</div>
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
      </div>
    </Link>
  );
}
