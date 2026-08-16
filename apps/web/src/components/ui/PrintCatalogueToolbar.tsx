"use client";

import type { PrintCatalogueFacets, PrintCatalogueSort } from "@/lib/prints";
import { FILTER_INPUT_CLASS, FILTER_LABEL_CLASS } from "./FilterBar";

const SORT_OPTIONS: { value: PrintCatalogueSort; label: string }[] = [
  { value: "card_code", label: "Card code" },
  { value: "name", label: "Name" },
  { value: "index_desc", label: "Market Index (high to low)" },
  { value: "index_asc", label: "Market Index (low to high)" },
  { value: "updated", label: "Recently updated" },
];

export interface PrintCatalogueFilters {
  q: string;
  treatment: string;
  rarity: string;
  sort: PrintCatalogueSort;
}

export const EMPTY_PRINT_FILTERS: PrintCatalogueFilters = {
  q: "",
  treatment: "",
  rarity: "",
  sort: "card_code",
};

export function hasActivePrintFilters(filters: PrintCatalogueFilters): boolean {
  return Boolean(filters.q || filters.treatment || filters.rarity);
}

/** Filter + sort controls for the print catalogue, sitting directly under the
 * catalogue intro (which owns the search box - see CatalogueIntro).
 *
 * Only treatment and rarity are offered, because those are the only two the
 * print API filters server-side (see GET /prints in
 * services/api/app/api/prints.py). Release/set is deliberately absent: the
 * catalogue returns `release_product_code` per item but has no release query
 * param or facet, and filtering it in the browser would silently only filter
 * the current page. Every option comes from `facets` - never a fabricated
 * value.
 *
 * Rarity briefly had a separate chip strip above this row, standing in for
 * the set navigation the design sketched. That was the wrong trade: it read
 * as set navigation without being it, and duplicated a filter that already
 * lives here. Until the API has a trustworthy release facet, rarity stays a
 * plain select alongside treatment and sort, and the page goes straight from
 * the intro into these controls.
 */
export function PrintCatalogueToolbar({
  filters,
  facets,
  onChange,
  onClear,
}: {
  filters: PrintCatalogueFilters;
  facets: PrintCatalogueFacets;
  onChange: (next: PrintCatalogueFilters) => void;
  onClear: () => void;
}) {
  function set<K extends keyof PrintCatalogueFilters>(
    key: K,
    value: PrintCatalogueFilters[K],
  ) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="mb-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {facets.treatments.length > 0 && (
          <label className={FILTER_LABEL_CLASS}>
            Treatment
            <select
              value={filters.treatment}
              onChange={(e) => set("treatment", e.target.value)}
              className={FILTER_INPUT_CLASS}
            >
              <option value="">All treatments</option>
              {facets.treatments.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}

        {facets.rarities.length > 0 && (
          <label className={FILTER_LABEL_CLASS}>
            Rarity
            <select
              value={filters.rarity}
              onChange={(e) => set("rarity", e.target.value)}
              className={FILTER_INPUT_CLASS}
            >
              <option value="">All rarities</option>
              {facets.rarities.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className={FILTER_LABEL_CLASS}>
          Sort
          <select
            value={filters.sort}
            onChange={(e) => set("sort", e.target.value as PrintCatalogueSort)}
            className={FILTER_INPUT_CLASS}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        {hasActivePrintFilters(filters) && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs font-medium text-text-muted underline-offset-2 hover:text-text-secondary hover:underline"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
