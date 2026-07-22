import { RarityBadge } from "@/components/RarityBadge";

export type FrameAccent = "gold" | "purple" | null;

/** Vault/slab-style frame for a card image (design brief §4) - inner
 * border + dark sleeve background so a card image never reads as a random
 * thumbnail. Falls back to a clean placeholder (card_code/rarity/set_code)
 * when `imageUrl` is missing, rather than a broken image or blank box.
 * `accent` adds a restrained (non-flashing) gold/purple edge glow for rare
 * variants - callers decide which cards qualify (see VariantBadge). */
export function CardImageFrame({
  imageUrl,
  alt,
  cardCode,
  rarity,
  setCode,
  accent = null,
  size = "md",
}: {
  imageUrl?: string | null;
  alt: string;
  cardCode: string;
  rarity?: string | null;
  setCode?: string | null;
  accent?: FrameAccent;
  size?: "sm" | "md" | "lg";
}) {
  const widthClass = size === "sm" ? "w-20" : size === "lg" ? "w-40" : "w-28";
  const accentClass = accent === "gold" ? "glow-gold" : accent === "purple" ? "glow-purple" : "";

  return (
    <div
      className={`vault-frame ${widthClass} aspect-[63/88] shrink-0 overflow-hidden ${accentClass}`}
    >
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt={alt} className="h-full w-full object-cover" />
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
