import { PRINT_SORT_VALUES, type PrintCatalogueParams, type PrintCatalogueSort } from "./prints";
import type { ReleaseCatalogueItem } from "./releases";

export interface PrintCatalogueFilters {
  q: string;
  releaseProductId: number | null;
  legacySet: string;
  rarities: string[];
  treatments: string[];
  sort: PrintCatalogueSort;
}

export const EMPTY_PRINT_FILTERS: PrintCatalogueFilters = {
  q: "", releaseProductId: null, legacySet: "", rarities: [], treatments: [], sort: "index_desc",
};

/** Collector refinements exclude the release/search browse context. */
export function collectorRefinementCount(filters: PrintCatalogueFilters): number {
  return filters.rarities.length + filters.treatments.length;
}

export function activeFilterCount(filters: PrintCatalogueFilters): number {
  return Number(Boolean(filters.releaseProductId || filters.legacySet)) + Number(Boolean(filters.q)) + filters.rarities.length + filters.treatments.length;
}
export const hasActivePrintFilters = (filters: PrintCatalogueFilters) => activeFilterCount(filters) > 0;

export function parseCatalogueState(params: URLSearchParams) {
  const id = Number(params.get("release_product_id"));
  const sort = params.get("sort") as PrintCatalogueSort;
  const offset = Number(params.get("offset"));
  return {
    filters: {
      q: (params.get("q") ?? "").slice(0, 128),
      releaseProductId: Number.isSafeInteger(id) && id > 0 ? id : null,
      legacySet: params.has("release_product_id") ? "" : params.get("set") ?? "",
      rarities: [...new Set(params.getAll("rarity").filter(Boolean))],
      treatments: [...new Set(params.getAll("treatment").filter(Boolean))],
      sort: PRINT_SORT_VALUES.includes(sort) ? sort : EMPTY_PRINT_FILTERS.sort,
    },
    offset: Number.isSafeInteger(offset) && offset > 0 ? offset : 0,
  };
}

export function resolveLegacyRelease(filters: PrintCatalogueFilters, releases: ReleaseCatalogueItem[]): PrintCatalogueFilters {
  if (filters.releaseProductId || !filters.legacySet) return filters;
  const matches = releases.filter((release) => release.official_code === filters.legacySet);
  return matches.length === 1 ? { ...filters, releaseProductId: matches[0].release_product_id, legacySet: "" } : filters;
}

export function buildCatalogueQuery(filters: PrintCatalogueFilters, offset = 0): string {
  const params = new URLSearchParams();
  if (filters.releaseProductId) params.set("release_product_id", String(filters.releaseProductId));
  else if (filters.legacySet) params.set("set", filters.legacySet);
  if (filters.q) params.set("q", filters.q);
  filters.rarities.forEach((value) => params.append("rarity", value));
  filters.treatments.forEach((value) => params.append("treatment", value));
  if (filters.sort !== EMPTY_PRINT_FILTERS.sort) params.set("sort", filters.sort);
  if (offset > 0) params.set("offset", String(offset));
  return params.size ? `?${params}` : "";
}

export function catalogueParams(filters: PrintCatalogueFilters): PrintCatalogueParams {
  return {
    release_product_id: filters.releaseProductId ?? undefined,
    set: filters.releaseProductId ? undefined : filters.legacySet || undefined,
    q: filters.q || undefined, rarity: filters.rarities, treatment: filters.treatments, sort: filters.sort,
  };
}

export function toggleFilter(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((entry) => entry !== value) : [...values, value];
}
