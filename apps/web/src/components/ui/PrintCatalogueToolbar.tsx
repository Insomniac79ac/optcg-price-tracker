"use client";

import { classifyRarityToken } from "@/lib/terminology";

import type { PrintCatalogueFacets, PrintCatalogueSort } from "@/lib/prints";

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

/** The catalogue's resting state - what /cards shows with no query string.
 *
 * `sort` is "index_desc", not "card_code". Ordered by card code the first page
 * is EB01-001 onward, and on 2026-09-01 that was 24 of 24 tiles reading
 * "Index unavailable": a market product whose opening screen showed no market
 * at all. Roughly 1% of the 4,316 printings carry an eligible price today, so
 * code order buries every one of them.
 *
 * Ordering by Market Index puts the priced printings first WITHOUT hiding
 * anything - the backend sorts on `(value is null, -value, id)`, so unpriced
 * prints follow the priced ones instead of being filtered out, and card-code
 * order stays one selection away in the Sort control.
 *
 * This is also the value `buildParams` compares against to decide whether
 * `sort` belongs in the URL, so the default stays absent from the query string
 * and any OTHER sort the collector picks is written to it explicitly. */
export const EMPTY_PRINT_FILTERS: PrintCatalogueFilters = {
  q: "",
  treatment: "",
  rarity: "",
  sort: "index_desc",
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
    // One bar, not a row of loose selects: a charcoal strip with a hairline
    // border so the controls read as belonging to the catalogue below them
    // rather than floating on the page. Filters sit left, sort is pushed
    // right from `sm` up; below that everything wraps onto two short rows
    // (treatment + rarity, then sort) instead of three tall stacked labels.
    <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-panel border border-border-muted bg-bg-elevated px-3 py-1.5">
      <span className="mono hidden text-[10px] font-medium uppercase tracking-[0.16em] text-text-faint sm:inline">
        Filters
      </span>

      {facets.treatments.length > 0 && (
        <FilterSelect
          label="Treatment"
          value={filters.treatment}
          onSelect={(value) => set("treatment", value)}
          placeholder="All treatments"
          options={facets.treatments.map((value) => ({ value, label: value }))}
        />
      )}

      {facets.rarities.length > 0 && (
        <FilterSelect
          label="Rarity"
          // The control offers two different kinds of thing, and the optgroups
          // below say which is which. The accessible name says so too, because
          // an option list read aloud one item at a time is exactly where "SP
          // Card" would otherwise be heard as a scarcity tier.
          accessibleName="Rarity or special print"
          value={filters.rarity}
          onSelect={(value) => set("rarity", value)}
          placeholder="All rarities"
          // The option VALUE is whatever the API's facet published, because
          // that is what `?rarity=` filters on - including the single
          // `SP CARD` value the backend expands to both source tokens (see
          // app/services/rarity_facets.py). Only the LABEL is translated, so
          // the dropdown never offers a collector "SPカード".
          groups={rarityOptionGroups(facets.rarities)}
        />
      )}

      {hasActivePrintFilters(filters) && (
        <button
          type="button"
          onClick={onClear}
          className="text-xs font-medium text-text-muted underline-offset-2 transition-colors hover:text-accent-teal-hover hover:underline"
        >
          Clear all
        </button>
      )}

      {/* Basis of the ordering, not a filter - so it sits apart from them,
          pushed right from `sm` up. Not below that: at 390px the two filter
          selects already fill the first row, and `ml-auto` then stranded the
          sort control alone against the right edge of a second row while
          everything else in the bar was left-aligned. Flowing normally, it
          simply wraps under "All treatments" and the bar reads as one
          left-aligned set of controls. */}
      <div className="sm:ml-auto">
        <FilterSelect
          label="Sort"
          value={filters.sort}
          onSelect={(value) => set("sort", value as PrintCatalogueSort)}
          options={SORT_OPTIONS}
        />
      </div>
    </div>
  );
}

const SELECT_CLASS =
  "min-w-0 rounded-control border border-border-default bg-bg-page px-2 py-1 text-xs text-text-primary transition-colors hover:border-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal";

/** One labelled control in the toolbar.
 *
 * The visible label is hidden below `sm`, where two controls have to share a
 * 358px row and every "Treatment"/"Rarity" caption is width the select
 * itself needs - the placeholder option ("All treatments") already says what
 * the control is. `aria-label` carries the name at every width regardless, so
 * hiding the caption never costs the accessible name. */
function FilterSelect({
  label,
  accessibleName,
  value,
  onSelect,
  options,
  groups,
  placeholder,
}: {
  label: string;
  /** The `aria-label`, where the visible caption is too short to be the whole
   * truth. The caption has to survive beside two other controls on a 640px
   * row; the accessible name has no such budget, so it carries the fuller
   * wording. Defaults to `label`. */
  accessibleName?: string;
  value: string;
  onSelect: (value: string) => void;
  /** A flat option list. Mutually exclusive with `groups`. */
  options?: { value: string; label: string }[];
  /** Options split into labelled `<optgroup>`s, for a control whose values
   * are not all the same kind of thing. */
  groups?: FilterOptionGroup[];
  /** Rendered as the empty/"no filter" option. Omit for a control like sort
   * that is always set to something. */
  placeholder?: string;
}) {
  return (
    <label className="flex min-w-0 items-center gap-1.5">
      <span className="hidden text-[11px] text-text-muted sm:inline">{label}</span>
      <select
        aria-label={accessibleName ?? label}
        value={value}
        onChange={(e) => onSelect(e.target.value)}
        className={SELECT_CLASS}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options?.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
        {groups?.map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

export interface FilterOptionGroup {
  label: string;
  options: { value: string; label: string }[];
}

/** The rarity control's options, split into the two kinds of thing the API's
 * one `?rarity=` parameter actually carries.
 *
 * The grouping is the point. "SP Card" and "Treasure Rare" are special
 * PRINT categories, not rungs on the scarcity ladder, and listing them
 * inline among Common/Rare/Super Rare is what made an SP print read as though
 * SP Card were its rarity. Under their own `<optgroup>` heading they are
 * plainly a different question - in the open list, in the accessible name,
 * and to a screen reader, which announces the group before the option.
 *
 * There is exactly ONE SP Card option, never one per source token. The
 * collapsing is the API's: `GET /prints` facets `SPカード` and `SP P` into a
 * single `SP CARD` value and expands that value back to both when filtering,
 * so the one option's population is the sum of both (see
 * app/services/rarity_facets.py). Nothing is merged, hidden or renamed here -
 * this function only labels and orders what the facet published, so a value
 * this build has never seen is still offered, under its own raw name, in the
 * group that does not claim to know what it is.
 */
function rarityOptionGroups(rarities: string[]): FilterOptionGroup[] {
  const rarityOptions: { value: string; label: string }[] = [];
  const specialOptions: { value: string; label: string }[] = [];
  const unknownOptions: { value: string; label: string }[] = [];

  for (const value of rarities) {
    const { rarity, specialPrint, unknownToken } = classifyRarityToken(value);
    if (rarity) rarityOptions.push({ value, label: rarity.label });
    else if (specialPrint) specialOptions.push({ value, label: specialPrint.label });
    else if (unknownToken) unknownOptions.push({ value, label: unknownToken });
  }

  return [
    { label: "Rarity", options: rarityOptions },
    { label: "Special print", options: specialOptions },
    { label: "Other", options: unknownOptions },
  ].filter((group) => group.options.length > 0);
}
