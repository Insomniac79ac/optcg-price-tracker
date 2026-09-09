/** Canvas primitives shared by every Card Pirate chart export.
 *
 * WHAT BELONGS HERE, AND WHAT DOES NOT. This module holds the things that are
 * the SAME whatever chart is being exported: the file's dimensions and pixel
 * ratio, the brand palette as canvas-usable literals, the Atlas mark's own
 * geometry, font resolution, filename hygiene, and the blob/anchor download.
 * Those are properties of "a Card Pirate chart as a PNG", not of any one
 * chart.
 *
 * PLAN CONSTRUCTION AND PLOT PAINTING STAY WITH THEIR CHART. The aggregate
 * Card Pirate Index and one exact print answer different questions with
 * differently-shaped data, and the temptation to unify their renderers is a
 * trap worth naming:
 *
 *   - The Index draws a DASHED JOIN across a snapshot gap, between the two
 *     real endpoints either side of it (methodology §13.4). That is a
 *     deliberate statement: the level is continuous, the archive is not.
 *   - The exact-print chart draws NOTHING across a break. Its strokes are
 *     separate paths with separate key spaces precisely so that a methodology
 *     change cannot become an unbroken line.
 *
 * Those are opposite rules for superficially similar shapes. A shared
 * "draw a gap" helper would have to take a flag that flips the meaning of the
 * data, and the first person to pass the wrong flag would publish a picture
 * that asserts something Atlas does not believe. So the gap and break drawing
 * deliberately lives in each chart's own renderer, and this module never
 * touches a series.
 *
 * NO NEW DEPENDENCY. `document.createElement("canvas")`, `Path2D`,
 * `canvas.toBlob` and an object URL - all browser primitives. A DOM-to-image
 * library would rasterise the page's own background and layout into the file,
 * which the self-contained requirement forbids.
 */

/** The exported canvas, in CSS pixels before `scale`. 16:9 so the file drops
 * into a post or a slide without either axis being cropped. */
export const EXPORT_WIDTH = 1200;
export const EXPORT_HEIGHT = 675;
/** Rasterised at 2x, so the type is still crisp when the image is opened at
 * full size rather than as a thumbnail. */
export const EXPORT_SCALE = 2;

/** Brand tokens, resolved to literals ON PURPOSE.
 *
 * The file must not depend on the page it came from, and a canvas cannot read
 * a CSS custom property anyway - `ctx.fillStyle = "var(--accent-gold)"` is
 * silently ignored and leaves the previous colour standing. These are the same
 * values `docs/interface_design_system.md` defines, so an export is the app's
 * palette rather than a second one.
 */
export const EXPORT_COLORS = {
  background: "#171717", // --bg-page
  panel: "#1F1F21",
  grid: "#2E2E31", // --border-muted
  textPrimary: "#F4F0E8",
  textSecondary: "#BDB6A8",
  textMuted: "#8C877D",
  parchment: "#E8DEC7", // --parchment, and SNKRDUNK's series colour
  gold: "#C79A4B", // --accent-gold, and the Market Index's series colour
  teal: "#4F8D86", // --accent-teal, and Yuyu-Tei's series colour
} as const;

/** Font stacks with real fallbacks. Callers pass the families actually loaded
 * on the page (next/font generates hashed names, so they cannot be
 * hardcoded); these are what a caller gets if it passes nothing. */
export interface ExportFonts {
  display: string;
  sans: string;
  mono: string;
}

export const DEFAULT_EXPORT_FONTS: ExportFonts = {
  display: 'Fraunces, Georgia, "Times New Roman", serif',
  sans: 'Manrope, "Helvetica Neue", Arial, sans-serif',
  mono: '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace',
};

/** The font families ACTUALLY loaded on the page.
 *
 * `next/font` generates hashed family names (`__Fraunces_1a2b3c`), so an
 * export cannot name them; it reads them off a live element instead and falls
 * back to the generic stacks when there is no DOM to read (SSR, tests).
 */
export function resolveExportFonts(element: Element | null): ExportFonts {
  if (!element || typeof getComputedStyle !== "function") return DEFAULT_EXPORT_FONTS;
  const style = getComputedStyle(element);
  const display = style.getPropertyValue("--font-display").trim();
  const sans = style.getPropertyValue("--font-sans").trim();
  const mono = style.getPropertyValue("--font-mono").trim();
  return {
    display: display || DEFAULT_EXPORT_FONTS.display,
    sans: sans || DEFAULT_EXPORT_FONTS.sans,
    mono: mono || DEFAULT_EXPORT_FONTS.mono,
  };
}

/** The Atlas mark's own path data, lifted verbatim from
 * `components/brand/AtlasMark.tsx`.
 *
 * There is one Atlas mark and this is it - the strings below are the same `d`
 * attributes that component renders, replayed through `Path2D` because a
 * canvas cannot mount a React SVG. Copying the GEOMETRY rather than inventing
 * a second mark is the point; if the mark changes, these change with it.
 * viewBox is 32x40.
 */
export const ATLAS_PATHS = {
  card: "M6 2 L24 2 L28 6 L28 34 A2 2 0 0 1 26 36 L6 36 A2 2 0 0 1 4 34 L4 4 A2 2 0 0 1 6 2 Z",
  fold: "M21.5 4 L25.5 7.5",
  route: "M8 30 Q9 22 14 19",
  north: "M16 10 L18.5 19 L13.5 19 Z",
  south: "M16 28 L18.5 19 L13.5 19 Z",
} as const;

/** Paint the Atlas mark at `size` CSS pixels wide, top-left at (x, y). */
export function drawAtlasMark(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  opacity: number,
): void {
  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.translate(x, y);
  ctx.scale(size / 32, size / 32);
  ctx.lineWidth = 1.6;
  ctx.strokeStyle = EXPORT_COLORS.parchment;
  ctx.stroke(new Path2D(ATLAS_PATHS.card));
  ctx.lineWidth = 1;
  ctx.stroke(new Path2D(ATLAS_PATHS.fold));
  ctx.setLineDash([1.4, 2.6]);
  ctx.stroke(new Path2D(ATLAS_PATHS.route));
  ctx.setLineDash([]);
  ctx.fillStyle = EXPORT_COLORS.gold;
  ctx.fill(new Path2D(ATLAS_PATHS.north));
  ctx.fillStyle = EXPORT_COLORS.teal;
  ctx.fill(new Path2D(ATLAS_PATHS.south));
  ctx.restore();
}

/** A canvas at `width x height` CSS pixels, rasterised at `scale`, already
 * filled with an OPAQUE ground.
 *
 * Opaque is not a style choice: a transparent bed is what turns light text
 * into unreadable text the moment the file is opened in a viewer that paints
 * white behind it, and a shared image is opened in viewers we do not choose.
 */
export function createExportCanvas(
  {
    width,
    height,
    scale,
    background,
  }: { width: number; height: number; scale: number; background: string },
  doc: Document,
): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } {
  const canvas = doc.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d context unavailable");
  ctx.scale(scale, scale);
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, width, height);
  return { canvas, ctx };
}

/** One path segment of a filename, reduced to a character class that cannot
 * travel anywhere it should not.
 *
 * Lowercased ASCII alphanumerics and single hyphens, nothing else - so a card
 * code with a slash, a window token this build has never heard of, or a name
 * carrying `..` all come out inert. Returns `fallback` when the input reduces
 * to nothing at all, because an empty segment would collapse two hyphens into
 * a filename that reads as a missing field.
 */
export function safeFilenameToken(value: string, fallback: string): string {
  const token = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return token || fallback;
}

/** `YYYY-MM-DD`, UTC. */
export function dayStamp(now: Date): string {
  return now.toISOString().slice(0, 10);
}

/** Hand a finished canvas to the reader as a file.
 *
 * NEVER THROWS AT THE CALL SITE. A canvas the UA refuses to encode, a blob
 * that comes back null, or a browser without `toBlob` all resolve to `false`,
 * so a caller can say so quietly instead of the page dying inside a click
 * handler.
 */
export async function downloadCanvasPng(
  canvas: HTMLCanvasElement,
  filename: string,
  doc: Document,
): Promise<boolean> {
  try {
    if (typeof canvas.toBlob !== "function") return false;
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/png");
    });
    if (!blob) return false;
    const url = URL.createObjectURL(blob);
    const anchor = doc.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    doc.body.appendChild(anchor);
    anchor.click();
    doc.body.removeChild(anchor);
    // Revoked on the next turn, so the navigation the click started has
    // already taken its reference to the blob.
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return true;
  } catch {
    return false;
  }
}
