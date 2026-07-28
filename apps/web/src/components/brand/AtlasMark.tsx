import type { SVGProps } from "react";

/**
 * Original CardPirate Atlas mark - a maritime-cartography identity built
 * from three motifs, none of which are official One Piece iconography:
 *   1. a vertical trading-card silhouette with a clipped top-right corner
 *      (a folded map/card corner, not a franchise symbol);
 *   2. a two-tone compass needle at its center (gold "north" / teal
 *      "south"), standing in for direction-finding/discovery;
 *   3. a faint dashed route line, hinting at a charted path across a map.
 * Deliberately no skull-and-crossbones, no straw hat, no Jolly Roger, no
 * copied franchise artwork - see docs/brand.md "Legal/IP constraints".
 *
 * Pure vector, no image asset - safe to inline anywhere (topbar, favicon
 * source, OG image render) with zero added bytes over the SVG markup
 * itself. Simple enough to stay legible at 16px (the outline + needle
 * silhouette is what survives at that size; the route line is a bonus
 * detail at larger sizes).
 */

export type AtlasMarkTone = "onDark" | "onLight";

const PALETTE: Record<
  AtlasMarkTone,
  { outline: string; pivot: string; needleNorth: string; needleSouth: string; route: string }
> = {
  // Default - the mark as it appears everywhere in the app's dark interface.
  onDark: {
    outline: "#E8DEC7", // weathered parchment
    pivot: "#171717", // deep background
    needleNorth: "#C79A4B", // treasure gold
    needleSouth: "#4F8D86", // sea-glass teal
    route: "#E8DEC7",
  },
  // For rare on-light contexts (print, email, light embeds).
  onLight: {
    outline: "#171717",
    pivot: "#F4F0E8",
    needleNorth: "#B3823A",
    needleSouth: "#3E726C",
    route: "#171717",
  },
};

export interface AtlasMarkProps extends SVGProps<SVGSVGElement> {
  tone?: AtlasMarkTone;
  /** Accessible name when the mark stands alone (no adjacent wordmark).
   * Pass `null` to render fully decorative (aria-hidden) when adjacent
   * text already carries the accessible name - e.g. inside AtlasLogo. */
  title?: string | null;
}

export function AtlasMark({ tone = "onDark", title = "CardPirate Atlas", ...rest }: AtlasMarkProps) {
  const c = PALETTE[tone];
  const decorative = title === null;

  return (
    <svg
      viewBox="0 0 32 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? true : undefined}
      {...rest}
    >
      {decorative ? null : <title>{title}</title>}

      {/* Card silhouette with a clipped (folded map corner) top-right edge. */}
      <path
        d="M6 2 L24 2 L28 6 L28 34 A2 2 0 0 1 26 36 L6 36 A2 2 0 0 1 4 34 L4 4 A2 2 0 0 1 6 2 Z"
        stroke={c.outline}
        strokeWidth={1.6}
        strokeOpacity={0.9}
      />
      {/* Fold crease echoing the clipped corner. */}
      <path d="M21.5 4 L25.5 7.5" stroke={c.outline} strokeWidth={1} strokeOpacity={0.45} strokeLinecap="round" />

      {/* Faint charted route, arcing toward the needle. */}
      <path
        d="M8 30 Q9 22 14 19"
        stroke={c.route}
        strokeWidth={1}
        strokeOpacity={0.4}
        strokeDasharray="1.4 2.6"
        strokeLinecap="round"
      />

      {/* Compass needle - gold north, teal south, sharing a center pivot. */}
      <path d="M16 10 L18.5 19 L13.5 19 Z" fill={c.needleNorth} />
      <path d="M16 28 L18.5 19 L13.5 19 Z" fill={c.needleSouth} />
      <circle cx={16} cy={19} r={1.5} fill={c.pivot} stroke={c.outline} strokeWidth={0.75} />
    </svg>
  );
}
