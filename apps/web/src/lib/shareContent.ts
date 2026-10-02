import type { PrintDetail, PrintCatalogueItem, PrintSibling } from "./prints";
import type { MarketValue, MarketValueWindow } from "./marketValue";
import type { ShareCardContent } from "./shareCard";
import { versionPrintingLabel } from "./terminology";
import { marketNumber, marketPercent } from "./marketValue";
import { releaseLabelEnglish } from "./releaseNames";

const jpy = (value: number | null) => value === null ? "Value unavailable" : `¥${value.toLocaleString("en-US")}`;
/** Use exact verified display assets or the canonical fallback, never a sibling. */
export function publicArtwork(print: Pick<PrintDetail, "display_image" | "image_url"> | PrintCatalogueItem | PrintSibling): string | null {
  return print.display_image?.exact_print_verified ? print.display_image.url : print.image_url;
}
/** Narrow canonical identity allowlist: no fuzzy crew guesses, affiliation from
 * colours/rarity, or assumption that every character belongs on a Wanted poster. */
export function socialFaction(print: Pick<PrintDetail, "card_code" | "name_en" | "name_jp">): { theme: "straw-hat" | "marine" | "neutral"; faction: string } {
  const names = [print.name_en, print.name_jp];
  if ((["OP05-119", "OP01-003"].includes(print.card_code) && names.some((n) => ["Monkey.D.Luffy", "Monkey D. Luffy", "モンキー・D・ルフィ"].includes(n ?? "")))
    || (print.card_code === "OP01-025" && names.some((n) => ["Roronoa Zoro", "Roronoa.Zoro", "ロロノア・ゾロ"].includes(n ?? "")))) return { theme: "straw-hat", faction: "STRAW HAT CREW" };
  if (print.card_code === "OP02-099" && names.some((n) => ["Sakazuki", "サカズキ"].includes(n ?? ""))) return { theme: "marine", faction: "NAVY · CHARACTER FILE" };
  return { theme: "neutral", faction: "ONE PIECE · CARD FILE" };
}
export function printShareContent(print: PrintDetail): ShareCardContent {
  const index = print.market_index;
  return { kind: "print", title: print.name_en || print.name_jp || print.card_code, code: print.card_code,
    identity: [versionPrintingLabel(print.official_asset_variant), print.language?.toUpperCase()].filter(Boolean).join(" · "),
    ...socialFaction(print), value: jpy(index.index_value_jpy),
    context: `${index.source_count} contributing source${index.source_count === 1 ? "" : "s"} · Japanese sources · this version${index.stale_sources.length ? " · Stale sources" : ""}`,
    date: index.freshest_observation_at ? `Latest observation ${index.freshest_observation_at.slice(0, 10)} · Source checks not reported` : "Observation time unknown · Source checks not reported" };
}
export function marketShareContent(data: MarketValue, requestedWindow: MarketValueWindow = data.movement.window): ShareCardContent {
  const release = data.scope_kind === "release";
  const valid = data.movement.window === requestedWindow && data.movement.available && data.movement.reason === "publishable" && marketNumber(data.movement.pct) !== null;
  return { kind: release ? "release" : "market", title: release ? releaseLabelEnglish(data.release_code, data.release_name).replace(`${data.release_code} — `, "") : "One Piece Market",
    code: data.release_code ?? undefined, identity: release ? "Sets on the Move / Japanese edition" : "Card Pirate Market Value",
    value: jpy(data.tracked_value.value_jpy),
    movement: valid ? { window: data.movement.window.toUpperCase(), value: marketPercent(data.movement.pct) } : undefined,
    context: `${data.tracked_value.priced_print_count.toLocaleString("en-US")} of ${data.tracked_value.total_physical_print_count.toLocaleString("en-US")} card variants priced${data.tracked_value.is_partial ? " · Partial coverage" : ""}`,
    date: `Published ${data.as_of.slice(0, 10)} · ${release ? "Release" : "Representative"} artwork; not necessarily basket constituents` };
}
