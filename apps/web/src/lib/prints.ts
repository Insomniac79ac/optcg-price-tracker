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
}

export interface PrintMarketIndex {
  card_print_id: number;
  index_version: number;
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
  rarity: string;
  card_type: string;
  treatment: string;
  language: string;
  release_product_code: string | null;
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
  treatment: string;
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
  rarity: string;
  card_type: string;
  colors: string[] | null;
  language: string;
  treatment: string;
  release_product_code: string | null;
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
  rarity: string;
  cardType: string;
  treatment: string;
  /** True when the treatment is worth surfacing on a tile (i.e. not the
   * plain base printing). */
  isDistinctTreatment: boolean;
  language: string;
  releaseCode: string | null;
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
 * collectible and always labelled. */
function isDistinctTreatment(treatment: string): boolean {
  const normalized = treatment.trim().toLowerCase();
  return normalized !== "" && normalized !== "normal" && normalized !== "base";
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
    cardType: item.card_type,
    treatment: item.treatment,
    isDistinctTreatment: isDistinctTreatment(item.treatment),
    language: item.language,
    releaseCode: item.release_product_code,
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
}

export interface PrintPriceSeriesTrend {
  source: string;
  price_type: string;
  latest_price_jpy: number | null;
  previous_price_jpy: number | null;
  change_jpy: number | null;
  change_pct: number | null;
  observation_count: number;
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
