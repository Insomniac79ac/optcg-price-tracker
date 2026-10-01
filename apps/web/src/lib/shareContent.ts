import type { PrintDetail } from "./prints";
import type { MarketValue } from "./marketValue";
import type { ShareCardContent } from "./shareCard";
import { printIdentity } from "./publicSeo";
import { releaseLabelEnglish } from "./releaseNames";
const jpy = (value: number | null) => value === null ? "Value unavailable" : `¥${value.toLocaleString("en-US")}`;
export function printShareContent(print: PrintDetail): ShareCardContent {
  const identity = printIdentity(print);
  const index = print.market_index;
  return { kind: "print", title: `${identity.name} ${print.card_code}`, identity: identity.detail, value: jpy(index.index_value_jpy), context: `Market Value estimate · ${index.source_count} contributing source${index.source_count === 1 ? "" : "s"}${index.stale_sources.length ? " · Stale sources" : ""}`, date: index.freshest_observation_at ? `Latest observation ${index.freshest_observation_at.slice(0, 10)} · Source checks not reported` : "Observation time unknown · Source checks not reported" };
}
export function marketShareContent(data: MarketValue): ShareCardContent {
  const release = data.scope_kind === "release";
  const movement = data.movement.available && data.movement.pct !== null && Number.isFinite(Number(data.movement.pct)) ? `${Number(data.movement.pct) > 0 ? "+" : ""}${Number(data.movement.pct).toFixed(2)}% over ${data.movement.window === "7d" ? "7 days" : "the selected period"}` : "Price movement unavailable";
  return { kind: release ? "release" : "market", title: release ? releaseLabelEnglish(data.release_code, data.release_name) : "How is the One Piece market doing?", identity: movement, value: jpy(data.tracked_value.value_jpy), context: `Tracked Market Value · ${data.tracked_value.priced_print_count.toLocaleString("en-US")} of ${data.tracked_value.total_physical_print_count.toLocaleString("en-US")} printings priced${data.tracked_value.is_partial ? " · Partial coverage" : ""}`, date: `Published ${data.as_of.slice(0, 10)} · Source checks not reported` };
}
