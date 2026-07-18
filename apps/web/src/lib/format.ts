export function formatJpy(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(value);
}

/** True if `new Date(value)` produced a real date - guards every date
 * formatter below against throwing on a garbage/malformed string (Intl's
 * formatters raise a RangeError on an Invalid Date rather than returning
 * something sensible). */
function isValidDate(date: Date): boolean {
  return !Number.isNaN(date.getTime());
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!isValidDate(date)) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!isValidDate(date)) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
  }).format(date);
}

export function cardDisplayName(card: {
  name_en: string | null;
  name_jp: string | null;
}): string {
  return card.name_en || card.name_jp || "Unknown card";
}

export function formatSignedJpy(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const formatted = formatJpy(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

export function formatSignedPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

// --- Newer, descriptively-named helpers ------------------------------------
//
// formatJpy/formatDate/formatDateTime/formatSignedJpy/formatSignedPct above
// are used across ~20 files with a compact "—" for missing data, which this
// dense, table-heavy app relies on - left as-is rather than churning every
// page's visual output. The functions below are the same underlying
// formatting with a descriptive "not available"/"missing" fallback instead,
// for call sites (new pages, or a MissingValue label) that want to say so
// explicitly rather than show a dash.

const NOT_AVAILABLE = "not available";
const MISSING = "missing";

/** Same formatting as formatJpy, with a descriptive null fallback. */
export function formatJPY(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_AVAILABLE;
  return formatJpy(value);
}

/** Same formatting as formatSignedPct, with a descriptive null fallback. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_AVAILABLE;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Plain (non-currency) grouped number, e.g. "1,234" - for counts/quantities,
 * not prices. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-US").format(value);
}

/** Generic "format if present, otherwise say so" wrapper - e.g.
 * formatNullable(item.notes, (n) => n.trim(), "not available") for a field
 * with no dedicated formatter of its own. */
export function formatNullable<T>(
  value: T | null | undefined,
  formatter: (value: T) => string,
  fallback: string = NOT_AVAILABLE,
): string {
  if (value === null || value === undefined) return fallback;
  return formatter(value);
}

/** A price specifically (as opposed to any other JPY amount) that's missing
 * reads better as "missing" than the generic "not available" - e.g. a
 * card with no recorded Yuyu-Tei/SNKRDUNK observation yet. */
export function formatPriceOrMissing(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  return formatJpy(value);
}
