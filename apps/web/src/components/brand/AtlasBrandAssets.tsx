import Image from "next/image";

/**
 * The supplied CardPirate Atlas raster brand artwork (`apps/web/public/brand/`).
 *
 * These are the approved assets and are always rendered as the real image -
 * never re-drawn in CSS/SVG, never substituted with an icon font or a text
 * lockup. They do *not* replace `AtlasMark`/`AtlasLogo`: that inline vector
 * mark stays the right choice for the favicon, the OG image and any context
 * where a raster download would be wasteful or a fill colour has to be
 * controlled. This module is for the places where the actual brand artwork
 * should be seen.
 *
 * Intrinsic pixel sizes are declared once here so every consumer gets the
 * correct aspect ratio and next/image can reserve layout space (no CLS)
 * without repeating magic numbers. The assets have transparent backgrounds,
 * so they sit directly on the app's own surfaces.
 *
 * `compass-divider.png` is supplied but currently unused: it shipped as the
 * intro -> catalogue transition on /cards and was removed in the following
 * pass for reading as a standalone ornament rather than a transition. The
 * file stays in public/brand; the component was deleted rather than left
 * behind as dead code.
 *
 * Every element carries `data-brand-asset`, which is how tests distinguish
 * chrome/decoration from real card artwork (see app/cards/page.test.tsx's
 * "no mock or demo dataset" guard).
 */

const LOGO = { src: "/brand/cardpirate-atlas-logo.png", width: 2172, height: 724 };
const MARK = { src: "/brand/cardpirate-atlas-mark.png", width: 1254, height: 1254 };

/** Low-contrast cartographic texture. Exported as data rather than a
 * component because its only caller renders it as a `fill` background layer
 * with its own object-position and overlay. */
export const ATLAS_MAP_TEXTURE_SRC = "/brand/atlas-map-texture.webp";

/** Full horizontal lockup (compass emblem + "CardPirate Atlas"). Decorative
 * by default: the header link that wraps it supplies the accessible name, so
 * a duplicate alt would concatenate into it. */
export function AtlasLogoImage({ className = "" }: { className?: string }) {
  return (
    <Image
      {...LOGO}
      data-brand-asset=""
      alt=""
      aria-hidden
      priority
      className={className}
    />
  );
}

/** Square compass/card emblem, for tight chrome (mobile header). */
export function AtlasMarkImage({ className = "" }: { className?: string }) {
  return (
    <Image
      {...MARK}
      data-brand-asset=""
      alt=""
      aria-hidden
      priority
      className={className}
    />
  );
}
