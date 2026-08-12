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

/** Search + filter + sort controls for the print catalogue.
 *
 * Only treatment and rarity are offered, because those are the only two the
 * print API filters server-side (see GET /prints in
 * services/api/app/api/prints.py). Release/set is deliberately absent: the
 * catalogue returns `release_product_code` per item but has no release query
 * param or facet, and filtering it in the browser would silently only filter
 * the current page. Every option comes from `facets` - never a fabricated
 * value.
 *
 * Search is submitted to the server, which matches card code, English name
 * and Japanese name (`OP01-013`, `Sanji`, `サンジ` all work) and returns
 * individual prints - a base and a parallel that both match come back as two
 * results, never one collapsed row.
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

  function submitSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const entered = new FormData(e.currentTarget).get("q");
    set("q", typeof entered === "string" ? entered.trim() : "");
  }

  return (
    <div className="mb-4 flex flex-col gap-2">
      <form onSubmit={submitSearch} className="flex gap-2">
        {/* Uncontrolled, keyed on the committed term: the URL is the single
            source of truth for `q`, and re-keying resets the box whenever a
            back/forward navigation or "Clear all" changes it - no state to
            keep in sync, so no sync effect. */}
        <input
          key={filters.q}
          type="search"
          name="q"
          defaultValue={filters.q}
          placeholder="Search by card code or name — OP01-013, Sanji, サンジ"
          aria-label="Search prints by card code, English name, or Japanese name"
          className={`${FILTER_INPUT_CLASS} flex-1`}
        />
        <button
          type="submit"
          className="rounded-control border border-border-default px-3 py-1 text-sm font-medium text-text-secondary hover:text-text-primary"
        >
          Search
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
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
            className="text-xs font-medium text-text-muted hover:text-text-secondary"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
