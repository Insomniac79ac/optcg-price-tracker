/** The one frontend data-access layer for public, print-centric card data.
 *
 * Every collector-facing surface built from here treats `card_print` as the
 * primary collectible identity: one visible item is exactly one print. Two
 * prints that bridge through the same legacy `cards` row (OP01-013 Sanji's
 * base and parallel, say) are separate items with separately-computed prices,
 * and nothing in this module ever reads a legacy `card_id`-keyed endpoint -
 * not `/cards`, not `/cards/catalogue`, not `/cards/{id}/market-index`, whose
 * card-keyed Market Index helper merges siblings by design (see
 * services/api/app/api/cards.py and docs/snkrdunk_verification_runbook.md).
 *
 * Requests go through apiGet, so they inherit NEXT_PUBLIC_API_URL and the
 * project's existing env-var conventions - no API URL or secret is introduced
 * here, and nothing server-side is exposed to the browser beyond what
 * `/prints` already serves publicly.
 */

import { apiGet, type PaginationMeta } from "./api";
import { resolveCardImageUrl } from "./cardImage";
import {
  artOrdinalLabel,
  classifyRarityToken,
  printingTypeTerm,
  rarityTerm,
  type Term,
} from "./terminology";

/** Print-scoped Market Index - the same shape as the legacy card-keyed
 * `MarketIndex` except keyed by `card_print_id`. Computed by
 * app.services.print_market_index, which filters observations strictly by
 * card_print_id. */
export interface PrintMarketIndexSourceValue {
  source: string;
  reference_type: string;
  evidence_type: "listing" | "transaction";
  value_jpy: number | null;
  observed_at: string | null;
  sample_size: number | null;
  stale: boolean;
  eligible: boolean;
  fallback_used: boolean;
  ineligible_reason: string | null;
  /** Why this value may not mean what its number says - see
   * app.services.source_semantics and @/lib/sourceConstraint, which owns the
   * collector-facing wording. Optional because an API older than the
   * source-semantics release omits the field entirely; absent and null are
   * both "nothing to say about this value". Never rendered raw. */
  constraint?: string | null;
}

export interface PrintMarketIndex {
  card_print_id: number;
  index_version: number;
  /** Which source-normalisation ruleset produced this index (see
   * app.services.source_semantics.SOURCE_SEMANTICS_VERSION). Debug/
   * reproducibility metadata only - deliberately never shown to collectors.
   * Optional for the same backward-compatibility reason as `constraint`. */
  source_semantics_version?: number;
  /** The span of the eligible source values behind index_value_jpy, or null
   * when fewer than two sources were eligible - see schemas.SourcePriceRangeOut.
   * Both endpoints are chosen by the backend from the same set that produced
   * the index; nothing here is derived in the browser. Optional for the same
   * backward-compatibility reason as `constraint` - a deployed API that
   * predates the field simply omits it. */
  source_price_range?: { low_jpy: number; high_jpy: number } | null;
  index_value_jpy: number | null;
  calculation_method: string;
  source_count: number;
  coverage_status: "full" | "limited" | "none";
  confidence: "high" | "medium" | "low";
  source_values: PrintMarketIndexSourceValue[];
  auxiliary_values: PrintMarketIndexSourceValue[];
  freshest_observation_at: string | null;
  stalest_eligible_source_at: string | null;
  stale_sources: string[];
  calculated_at: string;
}

/** Raw `GET /prints` item - see services/api/app/schemas.py
 * PrintCatalogueItemOut. */
export interface PrintCatalogueItem {
  card_print_id: number;
  canonical_card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  /** THIS printing's published rarity token, resolved server-side from
   * `card_prints.official_rarity` with the card-level value as a fallback.
   * Null only where the catalogue establishes neither - render nothing for it,
   * never "Unknown".
   *
   * It is a raw token, and it does not always name a rarity: `SPカード`,
   * `SP P` and `TR` name a special PRINT category instead. Never render it raw
   * and never label it "Rarity" without putting it through
   * `classifyRarityToken` first. */
  rarity: string | null;
  /** The card-level summary rarity from `canonical_cards`, served separately
   * and never a fallback for `rarity`. The only authoritative source of an
   * underlying rarity for a print whose own token names a special print, and
   * null wherever the catalogue established none - see schemas.py
   * CardPrintOut.canonical_rarity. Optional so an older API response parses. */
  canonical_rarity?: string | null;
  card_type: string;
  /** null once a printing carries no Atlas treatment classification. Render
   * no badge and no fallback label for it - never "Unclassified". */
  treatment: string | null;
  language: string;
  /** The product THIS printing appeared in - not the card's set. A reprint
   * carries the later product here, so it must never be labelled "Set". */
  release_product_code: string | null;
  /** The set the card was originally published in. null for promos, which
   * belong to no numbered set. Optional so an older API response parses. */
  original_set_code?: string | null;
  /** Bandai's own asset address for this printing - 'base', 'pN', 'rN'. Used
   * only to derive a printing type and, as a last resort, an art ordinal.
   * Never rendered raw, and never read as a rarity or a "parallel" claim. */
  official_asset_variant?: string | null;
  image_url: string | null;
  display_image: PrintDisplayImage | null;
  verification_status: string;
  market_index: PrintMarketIndex;
  source_coverage: string[];
  latest_observation_at: string | null;
}

export interface PrintCatalogueFacets {
  treatments: string[];
  rarities: string[];
  languages: string[];
  verification_statuses: string[];
}

export interface PrintCatalogueList {
  items: PrintCatalogueItem[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
  facets: PrintCatalogueFacets;
}

export interface PrintSibling {
  card_print_id: number;
  treatment: string | null;
  artwork_key: string | null;
  image_url: string | null;
  verification_status: string;
}

/** Which image to *show* for a print - see schemas.py DisplayImageOut.
 *
 * Additive and purely presentational. `source` is "bandai" when no cleaner
 * image has been verified for the print, in which case `url` repeats the
 * canonical `image_url` (SAMPLE watermark included). Identity always stays
 * with `image_url`/`artwork_key`. */
export interface PrintDisplayImage {
  url: string;
  source: string;
  exact_print_verified: boolean;
  /** Whether `url` came from a verified owned asset we mirrored, rather than
   * the original source or canonical URL. Optional because older responses
   * predate the field; absent reads as false. This is the only thing that
   * separates a verified official Card List asset from the canonical Bandai
   * fallback - both report `source: "bandai"`. */
  owned_asset_selected?: boolean;
  /** Present only when the API has verified geometry for this image. Lets a
   * client present the *card* rather than the canvas it sits on. Null for
   * canonical Bandai images (whose card already fills the asset) and whenever
   * the recorded geometry failed server-side validation. */
  geometry: PrintDisplayImageGeometry | null;
}

/** Where the card sits inside its source image, in source pixels. `x`/`y` are
 * a top-left origin and `width`/`height` span every card pixel inclusive of
 * both edges - the transparent rounded corners included, since those are part
 * of the card's shape. Everything outside this box was verified transparent. */
export interface PrintDisplayImageGeometry {
  canvas_px: { width: number; height: number };
  card_bbox_px: { x: number; y: number; width: number; height: number };
}

/** Raw `GET /prints/{id}` - see schemas.py CardPrintOut. */
export interface PrintDetail {
  card_print_id: number;
  canonical_card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  /** THIS printing's published rarity token, resolved server-side from
   * `card_prints.official_rarity` with the card-level value as a fallback.
   * Null only where the catalogue establishes neither - render nothing for it,
   * never "Unknown".
   *
   * It is a raw token, and it does not always name a rarity: `SPカード`,
   * `SP P` and `TR` name a special PRINT category instead. Never render it raw
   * and never label it "Rarity" without putting it through
   * `classifyRarityToken` first. */
  rarity: string | null;
  /** The card-level summary rarity from `canonical_cards`, served separately
   * and never a fallback for `rarity`. The only authoritative source of an
   * underlying rarity for a print whose own token names a special print, and
   * null wherever the catalogue established none - see schemas.py
   * CardPrintOut.canonical_rarity. Optional so an older API response parses. */
  canonical_rarity?: string | null;
  card_type: string;
  colors: string[] | null;
  language: string;
  treatment: string | null;
  /** The product THIS printing appeared in - not the card's set. A reprint
   * carries the later product here, so it must never be labelled "Set". */
  release_product_code: string | null;
  /** The set the card was originally published in. null for promos, which
   * belong to no numbered set. Optional so an older API response parses. */
  original_set_code?: string | null;
  /** Bandai's own asset address for this printing - 'base', 'pN', 'rN'. Used
   * only to derive a printing type and, as a last resort, an art ordinal.
   * Never rendered raw, and never read as a rarity or a "parallel" claim. */
  official_asset_variant?: string | null;
  artwork_key: string | null;
  image_url: string | null;
  display_image: PrintDisplayImage | null;
  verification_status: string;
  market_index: PrintMarketIndex;
  siblings: PrintSibling[];
}

export type PrintCatalogueSort = "card_code" | "name" | "index_desc" | "index_asc" | "updated";

export const PRINT_SORT_VALUES: PrintCatalogueSort[] = [
  "card_code",
  "name",
  "index_desc",
  "index_asc",
  "updated",
];

/** The API's canonical source names, as they appear in
 * `market_index.source_values[].source`. */
export const YUYUTEI = "yuyutei";
export const SNKRDUNK = "snkrdunk";
/** onepiece-cardgame.com. The API has always reported this source as
 * "bandai"; the collector-facing name for it is the official card list. */
export const BANDAI = "bandai";

const SOURCE_DISPLAY_NAME: Record<string, string> = {
  [YUYUTEI]: "Yuyu-Tei",
  [SNKRDUNK]: "SNKRDUNK",
  [BANDAI]: "Official ONE PIECE Card List",
};

export function sourceDisplayName(source: string): string {
  return SOURCE_DISPLAY_NAME[source] ?? source;
}

/** The UI model every public print surface renders from - a flat, display-
 * ready projection of one print. Deliberately carries no legacy `card_id`:
 * there is no field here a sibling print could leak through.
 *
 * `yuyuteiJpy`/`snkrdunkJpy` are read out of this print's own
 * `market_index.source_values`, which the backend already scoped to this
 * `card_print_id` - they are never fetched from a card-keyed endpoint and
 * never inferred from a sibling. */
export interface PrintUiModel {
  cardPrintId: number;
  cardCode: string;
  nameEn: string | null;
  nameJp: string | null;
  /** Display name: English where available, Japanese otherwise. */
  displayName: string;
  /** The raw published rarity token for this printing, kept for provenance
   * and for the fail-safe path only. Read `rarityTerm`/`specialPrint` for
   * anything a collector sees - this token may name a special print rather
   * than a rarity. */
  rarity: string | null;
  /** How scarce the card is, when that can be established honestly: this
   * printing's own token when it names an ordinary rarity, otherwise the
   * card-level `canonical_rarity` when THAT names one. Null when neither
   * does - which is the common case for a Treasure Rare - and callers then
   * render no rarity at all rather than filling the row. Nothing here is
   * inferred from a special-print token, an asset variant or a sibling. */
  rarityTerm: Term | null;
  /** True when `rarityTerm` came from the CARD-level `canonical_rarity` rather
   * than from this printing's own published token - which is the case for
   * every SP Card that has a rarity to show at all. Callers say so, because
   * "Super Rare" on an SP print is a fact about the card, established from its
   * own set, not a token printed on this catalogue entry. */
  rarityIsCardLevel: boolean;
  /** The special printing category - SP Card, Treasure Rare - or null. A
   * separate dimension from rarity and from printing: a print is commonly
   * two or three of them at once. */
  specialPrint: Term | null;
  /** The raw rarity token when this build recognises it as neither a rarity
   * nor a special print. Rendered verbatim so unfamiliar published evidence
   * reaches the collector instead of being silently dropped. */
  unknownRarityToken: string | null;
  cardType: string;
  treatment: string | null;
  /** True when the treatment is worth surfacing on a tile (i.e. not the
   * plain base printing, and not an unclassified one). */
  isDistinctTreatment: boolean;
  language: string;
  /** The product this printing appeared in. Rendered under "Found in", never
   * "Set" - for a reprint the two are different products. */
  releaseCode: string | null;
  /** The set the card was originally published in, where the API supplies it.
   * null for promos and for an API older than this field. */
  originalSetCode: string | null;
  /** Collector-facing printing type - "Alt Art" or "Reprint" - or null for a
   * base printing and for an asset family this build does not recognise. The
   * raw variant is never exposed. */
  printingType: Term | null;
  /** Which artwork of the card this is, e.g. "Art 2". Only a last-resort
   * disambiguator; callers show it when two tiles would otherwise read
   * identically. */
  artOrdinal: string | null;
  /** Ready to put straight into an <img src>: the print's verified display
   * image where one exists, the canonical Bandai artwork otherwise, rewritten
   * to a same-origin proxy path for hosts that refuse cross-origin embedding
   * (see src/lib/cardImage.ts). */
  imageUrl: string | null;
  /** The unrewritten canonical `card_print.image_url` exactly as the API
   * returned it, so identity provenance stays inspectable and nothing has to
   * un-proxy a URL. NOT necessarily what `imageUrl` renders. */
  sourceImageUrl: string | null;
  /** Which source `imageUrl` came from. Not sufficient on its own to tell a
   * verified image from the canonical fallback: "bandai" names both the
   * official Card List asset we mirrored and the canonical fallback. Pair it
   * with `imageOwnedAssetSelected`. */
  imageSource: string | null;
  /** Whether `imageUrl` is a verified asset we own and mirrored, as opposed to
   * an original source URL or the canonical fallback. Defaults to false when
   * the API omits it, so an older response is never mistaken for an owned
   * asset. Never inferred from the URL's hostname or shape. */
  imageOwnedAssetSelected: boolean;
  /** Whether the API has verified that `imageUrl` shows this exact print.
   * `null` means no display image was resolved, so no such evidence exists
   * either way and the canonical artwork is all there is. Consumers that
   * choose *which* prints to show (the catalogue intro's card fan) use this
   * to skip images known not to be the print; the tile itself shows whatever
   * image the print has. */
  imageExactPrintVerified: boolean | null;
  /** Verified geometry for `imageUrl`, when the API supplied it. Consumers
   * pass this straight to CardImageFrame, which uses it to fill the frame with
   * the card instead of the whole canvas - and ignores it unless the loaded
   * image's intrinsic size matches `canvas_px` exactly. */
  imageGeometry: PrintDisplayImageGeometry | null;
  marketIndexJpy: number | null;
  yuyuteiJpy: number | null;
  snkrdunkJpy: number | null;
  sourceCount: number;
  coverageStatus: PrintMarketIndex["coverage_status"];
  confidence: PrintMarketIndex["confidence"];
  /** Display names of the sources that actually contributed a value, e.g.
   * ["Yuyu-Tei"] for a limited-coverage print. */
  contributingSources: string[];
  latestObservationAt: string | null;
  /** Kept whole so MarketIndexValue/CoverageBadge can read the same
   * print-scoped index object rather than re-deriving it. */
  marketIndex: PrintMarketIndex;
}

function valueForSource(index: PrintMarketIndex, source: string): number | null {
  const match = index.source_values.find((entry) => entry.source === source);
  return match?.value_jpy ?? null;
}

/** "normal" is the plain base printing - not worth a badge on every tile.
 * Anything else (parallel, alt-art, reprint treatments) is a distinct
 * collectible and always labelled.
 *
 * null means the printing has no Atlas classification at all, which is not a
 * distinction to advertise: it gets no badge, and no invented label stands in
 * for it. */
function isDistinctTreatment(treatment: string | null): boolean {
  if (treatment === null) return false;
  const normalized = treatment.trim().toLowerCase();
  return normalized !== "" && normalized !== "normal" && normalized !== "base";
}

/** Splits one published rarity token into the dimensions a collector reads
 * separately, and finds an underlying rarity ONLY where one is already
 * established.
 *
 * The rule that matters is the one about what we refuse to do. When this
 * printing's own token names a special print - `SPカード`, `SP P`, `TR` -
 * there is no ordinary rarity in it, and the only other place an ordinary
 * rarity may come from is `canonical_rarity`, the card-level value the
 * importer writes solely where the card's own set publishes exactly one (see
 * canonical_import_apply "THE RARITY PROBLEM, AS RESOLVED"). Where that is
 * null, or is itself a special-print token, the answer is null and the caller
 * renders no rarity: nothing is derived from a sibling print, from an asset
 * variant, from the product, or from what the rarity "probably" is.
 *
 * `canonical_rarity` is never consulted when the printing's own token already
 * names an ordinary rarity - the print's own published value is the
 * authority, and the two agree for every ordinary print in the corpus anyway.
 */
function rarityFacts(item: PrintCatalogueItem | PrintDetail): {
  rarityTerm: Term | null;
  rarityIsCardLevel: boolean;
  specialPrint: Term | null;
  unknownRarityToken: string | null;
} {
  const facts = classifyRarityToken(item.rarity);
  if (facts.rarity) {
    return {
      rarityTerm: facts.rarity,
      rarityIsCardLevel: false,
      specialPrint: null,
      unknownRarityToken: null,
    };
  }
  // Only a KNOWN ordinary rarity is trustworthy enough to stand as the
  // underlying one; an unrecognised canonical token is left alone rather than
  // promoted into a "Rarity" row beside a special print.
  const underlying = rarityTerm(item.canonical_rarity);
  return {
    rarityTerm: underlying,
    rarityIsCardLevel: underlying !== null,
    specialPrint: facts.specialPrint,
    unknownRarityToken: facts.unknownToken,
  };
}

export function toPrintUiModel(item: PrintCatalogueItem | PrintDetail): PrintUiModel {
  const index = item.market_index;
  const contributingSources = index.source_values
    .filter((entry) => entry.value_jpy !== null)
    .map((entry) => sourceDisplayName(entry.source));

  return {
    cardPrintId: item.card_print_id,
    cardCode: item.card_code,
    nameEn: item.name_en,
    nameJp: item.name_jp,
    displayName: item.name_en || item.name_jp || item.card_code,
    rarity: item.rarity,
    ...rarityFacts(item),
    cardType: item.card_type,
    treatment: item.treatment,
    isDistinctTreatment: isDistinctTreatment(item.treatment),
    language: item.language,
    releaseCode: item.release_product_code,
    originalSetCode: item.original_set_code ?? null,
    printingType: printingTypeTerm(item.official_asset_variant),
    artOrdinal: artOrdinalLabel(item.official_asset_variant),
    // Presentation prefers the verified display image; identity stays with
    // image_url below. Falls back to the canonical URL when the API is older
    // than this field or no display image was resolved.
    // `||` not `??`: an empty display URL must fall back to the canonical
    // image rather than blank the tile. Geometry describes display_image.url
    // specifically, so it must not ride along when we did fall back.
    imageUrl: resolveCardImageUrl(item.display_image?.url || item.image_url),
    sourceImageUrl: item.image_url,
    imageSource: item.display_image?.url ? item.display_image.source : null,
    imageOwnedAssetSelected: item.display_image?.url
      ? item.display_image.owned_asset_selected === true
      : false,
    imageExactPrintVerified: item.display_image?.url
      ? item.display_image.exact_print_verified
      : null,
    imageGeometry: item.display_image?.url ? (item.display_image.geometry ?? null) : null,
    marketIndexJpy: index.index_value_jpy,
    yuyuteiJpy: valueForSource(index, YUYUTEI),
    snkrdunkJpy: valueForSource(index, SNKRDUNK),
    sourceCount: index.source_count,
    coverageStatus: index.coverage_status,
    confidence: index.confidence,
    contributingSources,
    latestObservationAt:
      "latest_observation_at" in item
        ? item.latest_observation_at
        : index.freshest_observation_at,
    marketIndex: index,
  };
}

export interface PrintCatalogueParams {
  q?: string;
  treatment?: string;
  rarity?: string;
  language?: string;
  verification_status?: string;
  sort?: PrintCatalogueSort;
  limit?: number;
  offset?: number;
}

/** GET /prints - the public print catalogue. One request per page; every
 * item already carries its own print-scoped Market Index, so a grid never
 * fans out to a per-card index request. */
export function fetchPrintCatalogue(
  params?: PrintCatalogueParams,
): Promise<PrintCatalogueList> {
  // Spread into a plain Record: apiGet's `params` is index-signature-typed
  // and PrintCatalogueParams (an interface) doesn't structurally satisfy that.
  // undefined values are dropped by apiGet's query builder.
  return apiGet<PrintCatalogueList>("/prints", { params: { ...params } });
}

/** GET /prints/{id} */
export function fetchPrint(printId: string | number): Promise<PrintDetail> {
  return apiGet<PrintDetail>(`/prints/${printId}`);
}

/** GET /prints/{id}/market-index - the print-scoped Market Index on its own.
 * The catalogue and detail responses already embed this, so callers rarely
 * need it; it exists so nothing is ever tempted to reach for the legacy
 * card-keyed `/cards/{id}/market-index` instead. */
export function fetchPrintMarketIndex(printId: string | number): Promise<PrintMarketIndex> {
  return apiGet<PrintMarketIndex>(`/prints/${printId}/market-index`);
}

export interface PrintPriceObservation {
  id: number;
  card_print_id: number;
  source_id: number;
  source: string;
  observed_at: string;
  price_type: string;
  price_jpy: number;
  condition_label: string | null;
  listing_count: number | null;
  raw_snapshot_id: number | null;
  /** Why this stored price may not mean what its number says - the same
   * vocabulary as `PrintMarketIndexSourceValue.constraint`, decided by
   * app.services.source_semantics and rendered through @/lib/sourceConstraint.
   * Optional because an API older than the source-semantics release omits it;
   * absent and null both read as "nothing to say about this observation". */
  constraint?: string | null;
  /** Whether SOURCE SEMANTICS disqualify this observation - NOT whether it
   * reached the Market Index (staleness and sample minimums live in the
   * index's own resolvers and are deliberately not applied to history; see
   * schemas.py PrintPriceObservationOut). Optional for the same
   * backward-compatibility reason as `constraint`, and absent reads as true:
   * an API that never classified an observation has not disqualified it. */
  eligible?: boolean;
  ineligible_reason?: string | null;
}

/** One (source, price_type) series' trend inside a print's price history -
 * see schemas.py PrintPriceSeriesTrendOut and
 * app.services.print_pricing.compute_print_price_series_trends.
 *
 * The backend always has a latest observation for a series it emits at all,
 * so `latest_price_jpy`/`latest_observed_at` are never null. What *is*
 * nullable is each window's change: `sufficient_history` is false for a
 * single-observation series, and even with history a `change_*_pct` stays
 * null unless a real observation exists at or before that window's cutoff -
 * the backend never fabricates one, and nothing here may substitute 0. */
export interface PrintPriceSeriesTrend {
  source: string;
  price_type: string;
  latest_price_jpy: number;
  /** ISO-8601 timestamp of the observation behind `latest_price_jpy`. */
  latest_observed_at: string;
  /** False when the series has fewer than two observations, in which case
   * every change_*_pct below is null. */
  sufficient_history: boolean;
  change_24h_pct: number | null;
  change_7d_pct: number | null;
  change_30d_pct: number | null;
}

export interface PrintPriceHistory {
  card_print_id: number;
  observations: PrintPriceObservation[];
  series: PrintPriceSeriesTrend[];
}

/** GET /prints/{id}/prices */
export function fetchPrintPrices(printId: string | number): Promise<PrintPriceHistory> {
  return apiGet<PrintPriceHistory>(`/prints/${printId}/prices`);
}

/** Print ids whose collector-facing label would still be ambiguous on this
 * page, and which therefore need an art ordinal to be told apart.
 *
 * The label a tile actually shows is name + card code + product + printing
 * type + rarity + special print. Two prints sharing all of it are
 * indistinguishable to a reader even though they are different printings with
 * different artwork - that is the case the ordinal exists for, and the only
 * one. Scoped to the prints on screen together: an ordinal on a tile whose
 * twin is 40 pages away would be noise a collector cannot act on.
 */
export function printsNeedingArtOrdinal(prints: PrintUiModel[]): Set<number> {
  const byLabel = new Map<string, PrintUiModel[]>();
  for (const print of prints) {
    const label = [
      print.displayName,
      print.cardCode,
      print.releaseCode ?? "",
      print.printingType?.label ?? "",
      // The rendered dimensions, not the raw token: two tiles reading
      // "SP Card" are indistinguishable to a collector even when one was
      // published as `SPカード` and the other as `SP P`.
      print.rarityTerm?.label ?? "",
      print.specialPrint?.label ?? "",
      print.unknownRarityToken ?? "",
    ].join("\u0000");
    const bucket = byLabel.get(label);
    if (bucket) bucket.push(print);
    else byLabel.set(label, [print]);
  }

  const needing = new Set<number>();
  for (const bucket of byLabel.values()) {
    if (bucket.length < 2) continue;
    for (const print of bucket) {
      // Only helps if this print actually has an ordinal to show. A base
      // printing has none, and inventing one would be a false distinction.
      if (print.artOrdinal) needing.add(print.cardPrintId);
    }
  }
  return needing;
}

/** The canonical identity behind a set of exact-code print records, or null.
 *
 * WHY THIS EXISTS. The legacy `cards` table disagrees with the canonical print
 * catalogue: as of 2026-09-01, 10 of 25 staging `cards` rows carry a
 * `card_code` whose canonical card is a DIFFERENT character (legacy OP01-001
 * is named "Monkey D. Luffy"; canonically OP01-001 is Roronoa Zoro). Their
 * `card_code`, rarity and variant agree with canonical - only `name_en` is
 * wrong - so the code is a sound join key and the legacy NAME is the thing
 * that must never be shown as the identity of a set of printings.
 *
 * FAIL CLOSED, DELIBERATELY. A name is returned only when EVERY record agrees
 * on one canonical card AND one name. Anything else - no records, two
 * canonical ids, two spellings - returns null, and the caller shows the card
 * code alone. The first record is never treated as the authority, and nothing
 * here does fuzzy matching, normalisation or majority voting: an inconsistent
 * corpus is a fact to report, not a tie to break.
 *
 * `items` must already be filtered to an exact `card_code` (see
 * PRINT_CATALOGUE_EXACT_CODE_NOTE) - this function does not filter, because a
 * disagreement is exactly what it is looking for.
 */
export interface CanonicalPrintIdentity {
  canonicalCardId: number;
  /** English name where the catalogue has one, else the Japanese name. */
  name: string;
}

export function resolveCanonicalPrintIdentity(
  items: PrintCatalogueItem[],
): CanonicalPrintIdentity | null {
  if (items.length === 0) return null;

  const canonicalIds = new Set(items.map((item) => item.canonical_card_id));
  if (canonicalIds.size !== 1) return null;

  // Compared as the catalogue stores them - no trimming, case folding or
  // punctuation normalisation, so "Portgas D. Ace" and "Portgas.D.Ace" are
  // treated as the disagreement they are rather than quietly merged.
  const names = new Set(items.map((item) => item.name_en ?? item.name_jp ?? ""));
  if (names.size !== 1) return null;

  const [name] = [...names];
  if (name === "") return null;

  return { canonicalCardId: [...canonicalIds][0], name };
}

/** Why a caller that searches the print catalogue by card code must still
 * filter the results by an exact `card_code`.
 *
 * `GET /prints?q=` is a substring ILIKE over the canonical `name_en`,
 * `name_jp` AND `card_code` (see app.services.print_catalogue._apply_filters),
 * so a code query can return another card's printing - by code prefix, or by a
 * name that happens to contain the string. The exact-code filter is what turns
 * a search result into an identity match; it is load-bearing, not defensive
 * decoration, and it is the only thing keeping a foreign printing off a card's
 * page. `card_code` is unique across `canonical_cards`, so an exact match
 * resolves to exactly one card. */
export const PRINT_CATALOGUE_EXACT_CODE_NOTE =
  "q is a substring search; results must be filtered to an exact card_code.";
