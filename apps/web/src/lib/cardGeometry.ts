/** Turning verified card geometry into a CSS placement.
 *
 * A display image is not always a picture of just a card. The verified
 * SNKRDUNK assets composite the card onto a larger landscape canvas with
 * transparent padding, so `object-fit: contain` fits the *canvas* to the
 * portrait frame and the card lands at roughly 43% of the frame's width.
 *
 * This module computes the placement that fills the frame with the card
 * instead, from the geometry the API supplies - never from constants about any
 * particular host. The overflow it produces falls strictly outside the
 * verified card box, which the evidence proved to be fully transparent.
 */

export interface CardBoxGeometry {
  canvas_px: { width: number; height: number };
  card_bbox_px: { x: number; y: number; width: number; height: number };
}

/** Absolute placement of the image inside the frame, all values in percent.
 * `width` is a percentage of the frame's width; `left`/`top` are percentages
 * of the frame's width and height respectively, matching how CSS resolves
 * `left`/`top` against a containing block. Height is left to the intrinsic
 * aspect ratio, so the image is never distorted. */
export interface CardBoxPlacement {
  widthPct: number;
  leftPct: number;
  topPct: number;
}

/** Grown by this many source pixels on every side before fitting.
 *
 * A safety tolerance in the only direction that is safe: it makes the box we
 * fit slightly *larger* than the verified card, so rounding can never bite
 * into a card pixel. It costs a fraction of a percent of fill and buys an
 * unconditional guarantee that the clip stays outside the card. */
const SAFETY_PAD_PX = 1;

export function isValidGeometry(geometry: CardBoxGeometry | null | undefined): boolean {
  if (!geometry) return false;
  const { canvas_px: canvas, card_bbox_px: box } = geometry;
  if (!canvas || !box) return false;
  const values = [canvas.width, canvas.height, box.x, box.y, box.width, box.height];
  if (values.some((v) => typeof v !== "number" || !Number.isFinite(v))) return false;
  if (canvas.width <= 0 || canvas.height <= 0) return false;
  if (box.width <= 0 || box.height <= 0) return false;
  if (box.x < 0 || box.y < 0) return false;
  if (box.x + box.width > canvas.width) return false;
  if (box.y + box.height > canvas.height) return false;
  return true;
}

/** True only when the loaded image is exactly the asset the geometry was
 * measured against. Any difference means the host changed the asset and the
 * stored box can no longer be trusted to describe it. */
export function matchesNaturalSize(
  geometry: CardBoxGeometry,
  naturalWidth: number,
  naturalHeight: number,
): boolean {
  return (
    naturalWidth === geometry.canvas_px.width && naturalHeight === geometry.canvas_px.height
  );
}

/**
 * Place `geometry`'s card box inside a frame of aspect `frameAspect`
 * (width / height) using contain semantics, and return where the whole canvas
 * has to sit for that to happen.
 *
 * Contain, not cover: the card box is fitted whole, so whichever axis is
 * tighter decides the scale and the card is never cropped. Because the frame
 * and the card are near-identical portrait ratios, the fit is usually
 * height-limited and the card ends up filling ~100% of the frame's height and
 * a hair under its width.
 */
export function placeCardBox(
  geometry: CardBoxGeometry,
  frameAspect: number,
): CardBoxPlacement {
  const { canvas_px: canvas, card_bbox_px: box } = geometry;

  // Fit a slightly grown box so no rounding can clip the card itself. Growing
  // is clamped to the canvas: we can never require pixels that don't exist.
  const padX = Math.min(SAFETY_PAD_PX, box.x, canvas.width - (box.x + box.width));
  const padY = Math.min(SAFETY_PAD_PX, box.y, canvas.height - (box.y + box.height));
  const fitX = box.x - padX;
  const fitY = box.y - padY;
  const fitW = box.width + padX * 2;
  const fitH = box.height + padY * 2;

  // Work in units of frame width; the frame is `1 x (1 / frameAspect)`.
  const frameH = 1 / frameAspect;
  // Scale, expressed as frame-widths per source pixel. Contain = the smaller.
  const scale = Math.min(1 / fitW, frameH / fitH);

  const widthPct = canvas.width * scale * 100;
  // Centre the fitted box, then shift so the canvas - not the box - is placed.
  const leftPct = ((1 - fitW * scale) / 2 - fitX * scale) * 100;
  const topPct = (((frameH - fitH * scale) / 2 - fitY * scale) / frameH) * 100;

  return { widthPct, leftPct, topPct };
}
