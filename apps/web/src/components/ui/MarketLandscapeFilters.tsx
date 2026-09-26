"use client";

import {
  basisLabel,
  type MarketBasis,
  type MarketFilterOption,
} from "@/lib/marketAnalytics";

import { releaseLabel, type ReleaseCatalogueItem } from "@/lib/releases";

/** Price basis and one aggregate release/rarity scope, all server supplied. */
export function MarketLandscapeFilters({
  bases,
  releases,
  rarities,
  selectedBasis,
  selectedRelease,
  selectedRarity,
  onBasisChange,
  onReleaseChange,
  onRarityChange,
  onClear,
}: {
  bases: MarketBasis[];
  releases: ReleaseCatalogueItem[] | null;
  rarities: MarketFilterOption[];
  selectedBasis: string;
  selectedRelease: string;
  selectedRarity: string;
  onBasisChange: (key: string) => void;
  onReleaseChange: (value: string) => void;
  onRarityChange: (value: string) => void;
  onClear: () => void;
}) {
  const scopeFiltered = Boolean(selectedRelease || selectedRarity);

  return (
    <div className="space-y-2.5">
      {/* The basis is the page's primary question - "read the market through what?" -
          so it gets segmented buttons rather than a third dropdown: the whole
          choice is visible at once and switching is one tap. At 390px the
          group wraps onto two rows instead of scrolling sideways. */}
      <fieldset className="min-w-0">
        <legend className="mb-1.5 text-xs font-medium text-text-muted">
          Price basis
        </legend>
        <div className="flex flex-wrap gap-1.5">
          {bases.map((basis) => {
            const active = basis.key === selectedBasis;
            return (
              <button
                key={basis.key}
                type="button"
                aria-pressed={active}
                onClick={() => onBasisChange(basis.key)}
                // Focus ring matches the sibling toggle in PrintPriceHistory
                // exactly, so keyboard focus looks the same on both of the
                // product's segmented controls rather than falling back to the
                // browser default on the newer one.
                className={`min-w-0 max-w-full truncate rounded-control border px-2.5 py-1 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 ${
                  active
                    ? "border-accent-teal bg-accent-teal/12 font-medium text-accent-teal-hover"
                    : "border-border-default bg-bg-page text-text-secondary hover:border-text-faint hover:text-text-primary"
                }`}
              >
                {basisLabel(basis)}
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset className="min-w-0 space-y-2 rounded-panel border border-border-muted bg-bg-elevated p-3">
        <legend className="px-1 text-xs font-medium text-text-muted">Scope</legend>
        {releases !== null && <ScopeSelect
          label="Release"
          value={selectedRelease}
          placeholder="All releases"
          options={releases.map((r) => ({ value: String(r.release_product_id), label: releaseLabel(r) }))}
          onSelect={onReleaseChange}
        />}

        <ScopeSelect
          label="Rarity"
          accessibleName="Rarity or special print"
          value={selectedRarity}
          placeholder="All rarities"
          options={rarities}
          onSelect={onRarityChange}
        />

        {scopeFiltered && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs font-medium text-text-muted underline-offset-2 transition-colors hover:text-accent-teal-hover hover:underline"
          >
            Clear all
          </button>
        )}
      </fieldset>
    </div>
  );
}

const SELECT_CLASS =
  "w-full min-w-0 rounded-control border border-border-default bg-bg-page px-2 py-1 text-xs text-text-primary transition-colors hover:border-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal";

/** Visible labels and full-width selectors remain readable on mobile. */
function ScopeSelect({
  label,
  accessibleName,
  value,
  placeholder,
  options,
  onSelect,
}: {
  label: string;
  accessibleName?: string;
  value: string;
  placeholder: string;
  options: MarketFilterOption[];
  onSelect: (value: string) => void;
}) {
  const empty = options.length === 0;
  const unlisted = value && !options.some((option) => option.value === value);
  return (
    <label className="grid min-w-0 gap-1.5">
      <span className="text-xs text-text-muted">{label}</span>
      <select
        aria-label={accessibleName ?? label}
        value={value}
        disabled={empty}
        onChange={(event) => onSelect(event.target.value)}
        className={`${SELECT_CLASS} ${empty ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <option value="">{empty ? `No ${label.toLowerCase()} options` : placeholder}</option>
        {unlisted && <option value={value}>Selected release</option>}
        {/* `value` and `label` are used for exactly what each is named for.
            Nothing here derives one from the other, which is how `OP01` and
            `OP-01` became two spellings of one set in the first place. */}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
