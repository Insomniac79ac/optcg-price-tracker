"use client";

import {
  basisLabel,
  type MarketBasis,
  type MarketFilterOption,
} from "@/lib/marketAnalytics";

/** The three controls above the market landscape: which price basis to read
 * it through, and which slice of the catalogue to read.
 *
 * EVERY OPTION IN THIS COMPONENT COMES FROM THE SERVER. The bases come from
 * `GET /analytics/market/bases`, the sets and rarities from
 * `GET /analytics/market/filters`, and there is no fallback list anywhere
 * below - a build with no response renders no options rather than a plausible
 * guess. That is what makes a fourth platform, or next season's set, appear
 * here without a frontend release, and it is why this file contains no
 * platform name and no set code.
 *
 * There is deliberately NO window control. The overview endpoint has no window
 * parameter: it reports what prices ARE, not how they moved, and a 7D/30D
 * selector that changed nothing would be a promise the data cannot keep. The
 * page says so in its own words further down, where a collector can read it,
 * rather than by rendering a dead control here.
 */
export function MarketLandscapeFilters({
  bases,
  sets,
  rarities,
  selectedBasis,
  selectedSet,
  selectedRarity,
  onBasisChange,
  onSetChange,
  onRarityChange,
  onClear,
}: {
  bases: MarketBasis[];
  sets: MarketFilterOption[];
  rarities: MarketFilterOption[];
  selectedBasis: string;
  selectedSet: string;
  selectedRarity: string;
  onBasisChange: (key: string) => void;
  onSetChange: (value: string) => void;
  onRarityChange: (value: string) => void;
  onClear: () => void;
}) {
  const scopeFiltered = Boolean(selectedSet || selectedRarity);

  return (
    <div className="space-y-2.5">
      {/* The basis is the page's primary question - "read the market through what?" -
          so it gets segmented buttons rather than a third dropdown: the whole
          choice is visible at once and switching is one tap. At 390px the
          group wraps onto two rows instead of scrolling sideways. */}
      <fieldset className="min-w-0">
        <legend className="mono mb-1.5 text-[10px] font-medium uppercase tracking-[0.16em] text-text-faint">
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

      {/* Scope filters share one bar, the same charcoal strip the print
          catalogue's toolbar uses, so the two surfaces read as one product. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-panel border border-border-muted bg-bg-elevated px-3 py-1.5">
        <span className="mono hidden text-[10px] font-medium uppercase tracking-[0.16em] text-text-faint sm:inline">
          Scope
        </span>

        <ScopeSelect
          label="Set"
          value={selectedSet}
          placeholder="All sets"
          options={sets}
          onSelect={onSetChange}
        />

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
      </div>
    </div>
  );
}

const SELECT_CLASS =
  "min-w-0 rounded-control border border-border-default bg-bg-page px-2 py-1 text-xs text-text-primary transition-colors hover:border-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal";

/** One labelled scope control, matching PrintCatalogueToolbar's FilterSelect
 * idiom: the visible caption is hidden below `sm` where the placeholder
 * already says what the control is, while `aria-label` carries the name at
 * every width so hiding the caption never costs the accessible name.
 *
 * An empty option list renders a disabled control saying so, rather than an
 * enabled dropdown containing only "All ..." - a control that cannot narrow
 * anything should not look like it can. */
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
  return (
    <label className="flex min-w-0 items-center gap-1.5">
      <span className="hidden text-[11px] text-text-muted sm:inline">{label}</span>
      <select
        aria-label={accessibleName ?? label}
        value={value}
        disabled={empty}
        onChange={(event) => onSelect(event.target.value)}
        className={`${SELECT_CLASS} ${empty ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <option value="">{empty ? `No ${label.toLowerCase()} options` : placeholder}</option>
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
