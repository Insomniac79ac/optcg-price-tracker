/** The current-state market landscape, as the browser sees it.
 *
 * WHAT THIS MODULE IS NOT ALLOWED TO DO, and the reason the rule is worth
 * stating: it computes no pricing semantics. Not one. Eligibility, the
 * platform floor, the sale-price constraint, which values may enter a median,
 * how a percentile is interpolated and which prints are in scope are all
 * decided by app.services.market_analytics and its neighbours, and arrive here
 * already decided. Every number below is READ from the response and rendered;
 * none is derived, re-summed, re-filtered or corrected.
 *
 * That is not fastidiousness. A client that recomputes even one of these
 * becomes a second pricing authority, and the day it disagrees with the print
 * page a collector clicks through to, the product is telling them two
 * different things about the same card. The backend module's docstring spends
 * a page on why `observed`, `usable`, `excluded_constrained` and `unavailable`
 * are four separate counts rather than one; the corresponding discipline on
 * this side is to pass all four through untouched, including - especially -
 * when one of them is null.
 *
 * NULL IS NEVER ZERO HERE. `observed_prints` and `excluded_constrained_prints`
 * are null for the Market Index basis because the index is derived rather than
 * observed and carries no constraint of its own; `median_jpy` is null when
 * nothing is priced; `p10`/`p90` are null below a minimum number of
 * constituents; `coverage_pct` is null for an empty scope, because 0/0 is not
 * 0%. Each of those is a different statement from "the answer is 0", and the
 * helpers below keep them apart rather than collapsing them into a falsy check.
 *
 * NO SOURCE NAME APPEARS IN THIS FILE. Bases come from the server, wording
 * comes from `sourceDisplayName`/`instrumentLabel`, and a platform this build
 * has never heard of renders with its own name and its own instrument. There
 * is no branch anywhere below that asks which platform it is looking at.
 */

import { apiGet } from "./api";
import { sourceDisplayName } from "./prints";
import { instrumentLabel } from "./sourceEvidence";

/** The basis grammar, identical to the one the print page's series selector
 * already publishes (`market_index` | `source:<name>`) so a collector who
 * picked a platform on a card and then opened analytics is picking the same
 * thing, spelled the same way, and a shared URL means one thing across the
 * product. */
export const MARKET_INDEX_BASIS = "market_index";

/** One selectable price basis - see MarketAnalyticsBasisOut. */
export interface MarketBasis {
  key: string;
  kind: "market_index" | "source";
  source: string | null;
  reference_type: string | null;
  evidence_type: string | null;
  available: boolean;
  unavailable_reason: string | null;
  usable_priced_prints: number;
}

export interface MarketBasesResponse {
  bases: MarketBasis[];
}

/** One selectable value for a catalogue filter. `value` goes on the wire,
 * `label` is read by a human, and the client uses each for exactly what it is
 * named for - it never derives one from the other. */
export interface MarketFilterOption {
  value: string;
  label: string;
}

export interface MarketFiltersResponse {
  sets: MarketFilterOption[];
  rarities: MarketFilterOption[];
}

export interface MarketScope {
  active_prints: number;
  set: string | null;
  rarity: string | null;
}

export interface MarketCoverage {
  /** Null for Market Index - nobody observes a derived value. */
  observed_prints: number | null;
  usable_priced_prints: number;
  /** Null for an empty scope: 0/0 is no answer, not 0%. */
  coverage_pct: number | null;
  /** Null for Market Index - a combination carries no constraint of its own. */
  excluded_constrained_prints: number | null;
  unavailable_prints: number;
}

export interface MarketCurrentPrice {
  constituent_count: number;
  median_jpy: number | null;
  p10_jpy: number | null;
  p90_jpy: number | null;
  unavailable_reason: string | null;
}

export interface MarketBucket {
  lower_jpy: number;
  upper_jpy: number | null;
  label: string;
  count: number;
}

export interface MarketIndexComposition {
  single_source_prints: number;
  multi_source_prints: number;
}

export interface MarketOverview {
  price_basis: string;
  kind: "market_index" | "source";
  source: string | null;
  reference_type: string | null;
  evidence_type: string | null;
  available: boolean;
  unavailable_reason: string | null;
  scope: MarketScope;
  coverage: MarketCoverage;
  current_price: MarketCurrentPrice;
  distribution: MarketBucket[];
  index_composition: MarketIndexComposition | null;
}

/** GET /analytics/market/bases */
export function fetchMarketBases(): Promise<MarketBasesResponse> {
  return apiGet<MarketBasesResponse>("/analytics/market/bases");
}

/** GET /analytics/market/filters - the SET and RARITY vocabularies the
 * overview accepts. Fetched rather than assembled: the values are published by
 * whoever owns the filter, so a set that ships next month is offered with no
 * release on this side. */
export function fetchMarketFilters(): Promise<MarketFiltersResponse> {
  return apiGet<MarketFiltersResponse>("/analytics/market/filters");
}

export interface MarketOverviewParams {
  priceBasis?: string;
  set?: string;
  rarity?: string;
}

/** GET /analytics/market/overview.
 *
 * There is no window parameter, and its absence is the tranche's own decision
 * rather than an omission: this endpoint reports what prices ARE, not how they
 * moved, because a 29-day archive whose 30d change is null on every print
 * cannot answer a movement question honestly yet. See the "Price movement"
 * block on the page, which says so where a collector can read it. */
export function fetchMarketOverview(params: MarketOverviewParams = {}): Promise<MarketOverview> {
  return apiGet<MarketOverview>("/analytics/market/overview", {
    params: {
      price_basis: params.priceBasis || undefined,
      set: params.set || undefined,
      rarity: params.rarity || undefined,
    },
  });
}

/** The collector-facing name for one basis - "Market Index", "Yuyu-Tei ·
 * Retail price", "SNKRDUNK · Current listing".
 *
 * Assembled from the SAME two helpers every other surface uses, so one
 * platform is one word wherever it appears and this page cannot drift from the
 * chart chips on a print page. A platform this build has never heard of falls
 * through `sourceDisplayName` to the server's own name, and an instrument it
 * has never heard of to a humanised form of the server's own token - so a
 * future Card Rush basis is labelled, not blank and not "Unknown source". */
export function basisLabel(basis: MarketBasis): string {
  if (basis.kind === "market_index") return "Market Index";
  const platform = sourceDisplayName(basis.source ?? "");
  const instrument = instrumentLabel(basis.reference_type);
  return instrument ? `${platform} · ${instrument}` : platform;
}

/** The platform half alone, for places too narrow for the instrument. */
export function basisPlatformLabel(basis: MarketBasis): string {
  if (basis.kind === "market_index") return "Market Index";
  return sourceDisplayName(basis.source ?? "");
}

/** The same label, from an overview response rather than a basis row.
 *
 * The overview carries `kind`, `source` and `reference_type` for exactly this
 * reason, so a heading can name the selected basis without the page having to
 * hold the basis list and the response in sync. */
export function overviewBasisLabel(overview: MarketOverview): string {
  return basisLabel({
    key: overview.price_basis,
    kind: overview.kind,
    source: overview.source,
    reference_type: overview.reference_type,
    evidence_type: overview.evidence_type,
    available: overview.available,
    unavailable_reason: overview.unavailable_reason,
    usable_priced_prints: overview.coverage.usable_priced_prints,
  });
}

/** Whether a basis key is one the server currently offers.
 *
 * Used to sanitise a key arriving from the URL. Deliberately a membership test
 * against the SERVER's list rather than a grammar check of our own: this build
 * has no opinion about which platforms exist, and a `?basis=` naming one that
 * has since been retired falls back to the default instead of requesting a
 * basis nothing can answer. */
export function isOfferedBasis(bases: MarketBasis[], key: string): boolean {
  return bases.some((basis) => basis.key === key);
}

/** Whether a filter value is one the server currently offers - the same
 * sanitisation, for `?set=` and `?rarity=`. */
export function isOfferedOption(options: MarketFilterOption[], value: string): boolean {
  return options.some((option) => option.value === value);
}

/** True when a statistic has an answer. Explicitly `!= null` rather than a
 * truthy test, because ¥0 is a real (if unlikely) price and null is not. */
export function hasValue(value: number | null | undefined): value is number {
  return value !== null && value !== undefined;
}

/** The tallest bar in a distribution, for scaling. 0 when every bucket is
 * empty, which the caller renders as "no bars" rather than dividing by it. */
export function peakBucketCount(distribution: MarketBucket[]): number {
  return distribution.reduce((peak, bucket) => Math.max(peak, bucket.count), 0);
}

/** Total constituents across the distribution.
 *
 * NOT a recomputation of `constituent_count` and never rendered in its place -
 * the server's own count is what the page shows. This exists only so the chart
 * can tell "every bucket is genuinely empty" from "there are no buckets",
 * which are different empty states. */
export function distributionTotal(distribution: MarketBucket[]): number {
  return distribution.reduce((total, bucket) => total + bucket.count, 0);
}
