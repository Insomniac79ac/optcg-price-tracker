"use client";

import { useState } from "react";

import { RarityBadge } from "@/components/RarityBadge";

export type FrameAccent = "gold" | "purple" | null;

/** Vault/slab-style frame for a card image (design brief §4) - inner
 * border + dark sleeve background so a card image never reads as a random
 * thumbnail. Falls back to a clean placeholder (card_code/rarity/set_code)
 * when `imageUrl` is missing *or* fails to load, rather than a broken image
 * or blank box. `accent` adds a restrained (non-flashing) gold/purple edge
 * glow for rare variants - callers decide which cards qualify (see
 * VariantBadge).
 *
 * Uses a plain <img>, not next/image, deliberately for now - see
 * docs/market_index.md "Image hosting" for why: Next's image optimizer
 * fetches, resizes and caches the source image through this app's own
 * server before ever serving it, which is a meaningfully bigger claim on a
 * third-party host's content (card.yuyu-tei.jp, the one real host currently
 * seeded) than a browser hotlinking it directly. Revisit once that host is
 * explicitly approved and added to next.config.ts's remotePatterns - and
 * the `object-contain`/lazy/async/referrer attributes below already match
 * what next/image would need, so that swap is additive when it happens. */
export function CardImageFrame({
  imageUrl,
  alt,
  cardCode,
  rarity,
  setCode,
  accent = null,
  size = "md",
  padded = false,
}: {
  imageUrl?: string | null;
  alt: string;
  cardCode: string;
  rarity?: string | null;
  setCode?: string | null;
  accent?: FrameAccent;
  /** "full" fills its container's width (the catalogue grid tile, where the
   * image is the dominant element) instead of a fixed px width. */
  size?: "sm" | "md" | "lg" | "full";
  /** Insets the artwork by a hair inside the frame. The frame is rounded and
   * clips its overflow, and a real card scan has the same 63:88 ratio as the
   * frame - so without this the rounding shaves the card's own corners off.
   * The inset is neutral empty space, never a crop or a zoom: the whole card
   * stays visible at every width. */
  padded?: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const widthClass =
    size === "full" ? "w-full" : size === "sm" ? "w-20" : size === "lg" ? "w-40" : "w-28";
  const shrinkClass = size === "full" ? "" : "shrink-0";
  const accentClass = accent === "gold" ? "glow-gold" : accent === "purple" ? "glow-purple" : "";
  const showImage = Boolean(imageUrl) && !broken;

  return (
    <div
      className={`vault-frame ${widthClass} ${shrinkClass} aspect-[63/88] overflow-hidden ${accentClass}`}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl!}
          alt={alt}
          className={`h-full w-full object-contain ${padded ? "p-1.5" : ""}`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-bg-card p-2 text-center">
          <div className="mono text-[11px] text-text-secondary">{cardCode}</div>
          {setCode && <div className="text-[11px] text-text-muted">{setCode}</div>}
          {rarity && <RarityBadge rarity={rarity} />}
        </div>
      )}
    </div>
  );
}
