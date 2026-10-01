/** Presentation contract for every current-price category, not just graded cards.
 * The existing public API can supply observed_at/stale only. The shared check,
 * availability and freshness fields must be explicitly adapted when published.
 * No calculation/publication time or client-side TTL is accepted here. */
export interface CurrentPriceFreshnessData {
  observedAt: string | null;
  successfullyCheckedAt?: string | null;
  availability?: "listed" | "no_listing" | "unknown";
  freshness?: "fresh" | "stale" | "unknown" | "historical";
}
function stamp(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return new Date(value).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}
export function CurrentPriceFreshness({ data }: { data: CurrentPriceFreshnessData }) {
  const observed = stamp(data.observedAt);
  const checked = stamp(data.successfullyCheckedAt);
  return <div className="mt-2 space-y-1 text-xs leading-5 text-text-secondary">
    <p>{observed ? <>Price observed <time dateTime={data.observedAt!}>{observed}</time></> : "Price observation time unknown"}</p>
    <p>{checked ? <>Successfully checked <time dateTime={data.successfullyCheckedAt!}>{checked}</time></> : "Successful check time not reported"}</p>
    <p>{data.freshness === "fresh" ? "Fresh source data" : data.freshness === "stale" ? "Stale source data" : data.freshness === "historical" ? "Historical price" : "Freshness not confirmed"}{data.availability ? ` · ${data.availability === "listed" ? "Listed" : data.availability === "no_listing" ? "No listing" : "Availability unknown"}` : ""}</p>
  </div>;
}
