import { redirect } from "next/navigation";

/** Where /market/movers sends visitors while it is parked: the public
 * catalogue, ordered by Market Index, highest first.
 *
 * That is exactly what the retired page showed - `GET /prints?sort=index_desc`
 * rendered as print tiles - so nobody loses a view, and /cards keeps the
 * filters, pagination and search the standalone page never had. */
export const MARKET_MOVERS_REDIRECT = "/cards?sort=index_desc";

/** /market/movers, temporarily retired (tranche 1A, 2026-08-19).
 *
 * The page that lived here ranked printings by current Market Index. It was a
 * snapshot ranking, not movement - the payload carries no history, no deltas
 * and no trend - which made it a second public catalogue surface differing
 * from /cards only by sort order, and a third item in a two-destination
 * public product.
 *
 * So the route now redirects instead of rendering, and deliberately holds no
 * catalogue UI of its own.
 *
 * `redirect()` answers 307 (temporary), never 308: this route is expected
 * back. Once there is enough price history for genuine movement analytics -
 * real gainers and losers over 7/30/90 days, not a re-sorted catalogue - the
 * page returns here, and a permanent redirect cached in every visitor's
 * browser would be in the way when it does.
 *
 * The Market Index itself is unchanged and undiminished by this: it is still
 * calculated the same way (app.services.market_index), still shown on every
 * catalogue tile, and still leads every /prints/{id} page. What went away is a
 * page, not a metric.
 */
export default function MarketMoversPage() {
  redirect(MARKET_MOVERS_REDIRECT);
}
