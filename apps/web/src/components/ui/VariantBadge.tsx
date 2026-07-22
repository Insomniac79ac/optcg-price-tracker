import { Badge } from "./Badge";

// Restrained accent only - no shine/flash animation (see docs "do not do"
// list). Manga/SP/SEC read as gold (rarest-feeling), Parallel/Alt Art as
// purple (alternate-art feeling) - kept as two families rather than a
// color per variant so the accent stays legible at a glance.
const GOLD_VARIANTS = new Set(["manga", "sp", "sec"]);
const PURPLE_VARIANTS = new Set(["parallel", "alt_art", "alt art", "altart"]);

function toneClass(variant: string): string {
  const key = variant.trim().toLowerCase();
  if (GOLD_VARIANTS.has(key)) {
    return "bg-accent-gold/10 text-accent-gold ring-1 ring-inset ring-accent-gold/40";
  }
  if (PURPLE_VARIANTS.has(key)) {
    return "bg-violet-500/12 text-violet-300 ring-1 ring-inset ring-violet-500/35";
  }
  return "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30";
}

/** Shared with CardImageFrame/CardVaultTile so a rare variant gets the same
 * restrained gold/purple glow on its frame as its badge uses. */
export function accentForVariant(variant: string | null | undefined): "gold" | "purple" | null {
  if (!variant) return null;
  const key = variant.trim().toLowerCase();
  if (GOLD_VARIANTS.has(key)) return "gold";
  if (PURPLE_VARIANTS.has(key)) return "purple";
  return null;
}

export function VariantBadge({ variant }: { variant: string | null | undefined }) {
  if (!variant) return <span className="text-text-faint">base</span>;
  return <Badge label={variant} className={toneClass(variant)} />;
}
