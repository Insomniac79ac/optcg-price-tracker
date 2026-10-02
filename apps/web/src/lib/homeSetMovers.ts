import { marketNumber, type MarketValueRelease } from "./marketValue";

/** Presentation ranking only. Never recompute comparable returns or fill gaps.
 * Compare one publication date, not a newer release against an older snapshot. */
export function homeSetMovers(releases: readonly MarketValueRelease[], limit = 4): MarketValueRelease[] {
  const dates = releases.map((item) => item.as_of).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date));
  const latest = dates.sort().at(-1);
  return releases.filter((item) => item.as_of === latest && item.seven_day.available
    && item.seven_day.reason === "publishable" && marketNumber(item.seven_day.pct) !== null)
    .sort((a, b) => Math.abs(marketNumber(b.seven_day.pct)!) - Math.abs(marketNumber(a.seven_day.pct)!)
      || a.release_product_id - b.release_product_id).slice(0, Math.max(0, limit));
}
