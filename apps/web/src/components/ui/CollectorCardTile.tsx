import Link from "next/link";

import { RarityBadge } from "@/components/RarityBadge";
import type { CardCatalogueItem } from "@/lib/api";
import { cardDisplayName, formatDate } from "@/lib/format";
import { CardImageFrame } from "./CardImageFrame";
import { MarketIndexValue } from "./MarketIndexValue";
import { accentForVariant } from "./VariantBadge";

/** The public /cards catalogue grid tile (design brief Phase 5) - card
 * artwork dominates, Market Index is the primary number, everything else is
 * secondary text. The whole tile is one link (no hover-only affordance) so
 * it's a single tab stop with a visible focus ring, and its accessible name
 * carries name + card code + set so a screen-reader user gets full identity
 * from the link alone, without repeating every metadata field verbatim. */
export function CollectorCardTile({ card }: { card: CardCatalogueItem }) {
  const name = cardDisplayName(card);
  const accent = accentForVariant(card.variant);
  const accessibleName = `${name}, ${card.card_code}, ${card.set_code}${
    card.rarity ? `, ${card.rarity}` : ""
  }`;

  return (
    <Link
      href={`/cards/${card.id}`}
      aria-label={accessibleName}
      className="vault-card group flex flex-col overflow-hidden rounded-panel focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-gold focus-visible:ring-offset-2 focus-visible:ring-offset-bg-page"
    >
      <CardImageFrame
        imageUrl={card.image_url}
        alt={`${name} (${card.card_code})`}
        cardCode={card.card_code}
        rarity={card.rarity}
        setCode={card.set_code}
        accent={accent}
        size="full"
      />
      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <div className="flex items-start justify-between gap-1.5">
          <span className="truncate text-sm font-medium text-text-primary">{name}</span>
          {card.rarity && <RarityBadge rarity={card.rarity} />}
        </div>
        <div className="mono flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-text-muted">
          <span>{card.card_code}</span>
          <span aria-hidden="true">·</span>
          <span>{card.set_code}</span>
          {card.variant && card.variant !== "base" && (
            <>
              <span aria-hidden="true">·</span>
              <span className="normal-case text-text-faint">{card.variant}</span>
            </>
          )}
        </div>

        <div className="mt-auto pt-1.5">
          <MarketIndexValue index={card.market_index} size="sm" />
          {card.market_index.freshest_observation_at && (
            <div className="mt-1 text-[10px] text-text-faint">
              Updated {formatDate(card.market_index.freshest_observation_at)}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
