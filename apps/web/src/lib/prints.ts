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

const SOURCE_DISPLAY_NAME: Record<string, string> = {
  [YUYUTEI]: "Yuyu-Tei",
  [SNKRDUNK]: "SNKRDUNK",
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
  /** Ready to put straight into an <img src>: the original URL for hosts that
   * embed cross-origin, a same-origin proxy path for hosts that refuse to
   * (see src/lib/cardImage.ts). */
  imageUrl: string | null;
  /** The unrewritten `card_print.image_url` exactly as the API returned it,
   * so provenance stays inspectable and nothing has to un-proxy a URL. */
  sourceImageUrl: string | null;
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
    imageUrl: resolveCardImageUrl(item.image_url),
    sourceImageUrl: item.image_url,
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
