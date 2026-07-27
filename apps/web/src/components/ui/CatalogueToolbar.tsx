"use client";

import { useState } from "react";

import type { CardCatalogueFacets, CardCatalogueSort } from "@/lib/api";
import { FILTER_INPUT_CLASS, FILTER_LABEL_CLASS } from "./FilterBar";

const SORT_OPTIONS: { value: CardCatalogueSort; label: string }[] = [
  { value: "card_code", label: "Card code" },
  { value: "name", label: "Name" },
  { value: "index_desc", label: "Market Index (high to low)" },
  { value: "index_asc", label: "Market Index (low to high)" },
  { value: "updated", label: "Recently updated" },
];

export interface CatalogueFilters {
  q: string;
  set_code: string;
  rarity: string;
  language: string;
  variant: string;
  sort: CardCatalogueSort;
}

export const EMPTY_CATALOGUE_FILTERS: CatalogueFilters = {
  q: "",
  set_code: "",
  rarity: "",
  language: "",
  variant: "",
  sort: "card_code",
};

export function hasActiveFilters(filters: CatalogueFilters): boolean {
  return Boolean(
    filters.q || filters.set_code || filters.rarity || filters.language || filters.variant,
  );
}

/** Search/filter/sort controls for the /cards catalogue (design brief Phase
 * 7) - a controlled component: the page owns filter state (encoded into the
 * URL, so back/forward and shared links restore it) and passes it down,
 * this just renders the inputs and reports changes back up. Only ever
 * offers filter values that exist in `facets` - see
 * app.services.card_catalogue.get_catalogue_facets - never a fabricated
 * option. */
export function CatalogueToolbar({
  filters,
  facets,
  onChange,
  onClear,
}: {
  filters: CatalogueFilters;
  facets: CardCatalogueFacets;
  onChange: (next: CatalogueFilters) => void;
  onClear: () => void;
}) {
  const [qInput, setQInput] = useState(filters.q);

  function set<K extends keyof CatalogueFilters>(key: K, value: CatalogueFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    set("q", qInput.trim());
  }

  return (
    <div className="mb-4 flex flex-col gap-2">
      <form onSubmit={submitSearch} className="flex gap-2">
        <input
          type="text"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Search by name or card code…"
          aria-label="Search by name or card code"
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
        <label className={FILTER_LABEL_CLASS}>
          Set
          <select
            value={filters.set_code}
            onChange={(e) => set("set_code", e.target.value)}
            className={FILTER_INPUT_CLASS}
          >
            <option value="">All sets</option>
            {facets.set_codes.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

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

        <label className={FILTER_LABEL_CLASS}>
          Language
          <select
            value={filters.language}
            onChange={(e) => set("language", e.target.value)}
            className={FILTER_INPUT_CLASS}
          >
            <option value="">All languages</option>
            {facets.languages.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>

        {facets.variants.length > 0 && (
          <label className={FILTER_LABEL_CLASS}>
            Variant
            <select
              value={filters.variant}
              onChange={(e) => set("variant", e.target.value)}
              className={FILTER_INPUT_CLASS}
            >
              <option value="">All variants</option>
              {facets.variants.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className={FILTER_LABEL_CLASS}>
          Sort
          <select
            value={filters.sort}
            onChange={(e) => set("sort", e.target.value as CardCatalogueSort)}
            className={FILTER_INPUT_CLASS}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        {hasActiveFilters(filters) && (
          <button
            type="button"
            onClick={() => {
              setQInput("");
              onClear();
            }}
            className="text-xs font-medium text-text-muted hover:text-text-secondary"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
