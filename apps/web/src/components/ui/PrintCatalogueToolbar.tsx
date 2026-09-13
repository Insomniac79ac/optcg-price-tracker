"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { releaseDisplayName } from "@/lib/releaseNames";
import { classifyRarityToken } from "@/lib/terminology";
import type { PrintCatalogueFacets, PrintCatalogueSort } from "@/lib/prints";

const MOBILE_QUERY = "(max-width: 63.999rem)";

const SORT_OPTIONS: { value: PrintCatalogueSort; label: string }[] = [
  { value: "card_code", label: "Card code" },
  { value: "name", label: "Name" },
  { value: "index_desc", label: "Market Index ↓" },
  { value: "index_asc", label: "Market Index ↑" },
  { value: "updated", label: "Recently updated" },
];

export interface PrintCatalogueFilters {
  q: string;
  release: string;
  treatment: string;
  rarity: string;
  sort: PrintCatalogueSort;
}

export const EMPTY_PRINT_FILTERS: PrintCatalogueFilters = {
  q: "",
  release: "",
  treatment: "",
  rarity: "",
  sort: "index_desc",
};

export function hasActivePrintFilters(filters: PrintCatalogueFilters): boolean {
  return Boolean(filters.release || filters.q || filters.treatment || filters.rarity);
}

function subscribeToMobile(onChange: () => void): () => void {
  const media = window.matchMedia(MOBILE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function useMobileCatalogue(): boolean {
  return useSyncExternalStore(
    subscribeToMobile,
    () => window.matchMedia(MOBILE_QUERY).matches,
    () => false,
  );
}

/** One filter model with two responsive presentations.
 *
 * Desktop commits the URL when a rail field changes. Mobile uses the same
 * field component against a draft inside a modal sheet and commits it once
 * on Apply. The URL remains the only state that fetches data; reopening the
 * sheet starts from that committed state. */
export function PrintCatalogueToolbar({
  filters,
  releases,
  releaseStatus,
  onRetryReleases,
  facets,
  onChange,
  legend,
}: {
  filters: PrintCatalogueFilters;
  releases: { value: string; label: string }[];
  releaseStatus: "loading" | "ready" | "error";
  onRetryReleases: () => void;
  facets: PrintCatalogueFacets;
  onChange: (next: PrintCatalogueFilters) => void;
  legend?: ReactNode;
}) {
  const mobile = useMobileCatalogue();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(filters);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const returnFocus = triggerRef.current;
    document.body.style.overflow = "hidden";

    const focusFrame = window.requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLElement>(
        "select, button:not([disabled]), input, [href], [tabindex]:not([tabindex='-1'])",
      )?.focus();
    });

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        "select:not([disabled]), button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      )].filter((element) => element.getClientRects().length > 0 || element === document.activeElement);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
      returnFocus?.focus();
    };
  }, [open]);

  if (!mobile) {
    return (
      <aside className="sticky top-[calc(var(--header-h)+1rem)] rounded-panel border border-border-default bg-bg-surface p-4" aria-labelledby="catalogue-filters-title">
        <p className="mono text-[10px] font-semibold uppercase tracking-[0.18em] text-accent-gold">Refine the atlas</p>
        <h2 id="catalogue-filters-title" className="mt-1 font-display text-lg font-semibold text-text-primary">Collector filters</h2>
        <div className="mt-4 flex flex-col gap-4">
          <CatalogueFilterFields
            filters={filters}
            releases={releases}
            releaseStatus={releaseStatus}
            facets={facets}
            onChange={onChange}
          />
        </div>
        {releaseStatus === "error" && <ReleaseRetry onRetry={onRetryReleases} />}
        {hasActivePrintFilters(filters) && (
          <button type="button" onClick={() => onChange(EMPTY_PRINT_FILTERS)} className="mt-5 min-h-11 w-full rounded-control border border-border-default px-3 text-xs font-medium text-text-secondary hover:border-text-faint hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60">
            Clear filters
          </button>
        )}
        {legend && <div className="mt-5 border-t border-border-muted pt-4">{legend}</div>}
      </aside>
    );
  }

  const selectedCount = [filters.release, filters.rarity, filters.treatment].filter(Boolean).length;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          setDraft(filters);
          setOpen(true);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="fixed bottom-[calc(5.25rem+env(safe-area-inset-bottom))] right-4 z-30 inline-flex min-h-11 items-center gap-2 rounded-full border border-accent-gold/70 bg-bg-elevated px-4 text-xs font-semibold text-parchment shadow-[0_8px_30px_rgba(0,0,0,0.45)] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal"
      >
        <FilterIcon />
        Filters{selectedCount > 0 ? ` · ${selectedCount}` : ""}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 bg-black/65" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-catalogue-filters-title"
            className="fixed inset-x-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] max-h-[calc(100dvh-5rem-env(safe-area-inset-bottom))] overflow-y-auto rounded-t-modal border border-border-default bg-bg-elevated px-5 pb-5 pt-4 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="mono text-[10px] font-semibold uppercase tracking-[0.18em] text-accent-gold">Refine the atlas</p>
                <h2 id="mobile-catalogue-filters-title" className="mt-1 font-display text-2xl font-semibold text-text-primary">Filters</h2>
              </div>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close filters" className="grid min-h-11 min-w-11 place-items-center rounded-control border border-border-default text-xl text-text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal">
                ×
              </button>
            </div>

            <div className="mt-5 flex flex-col gap-5">
              <CatalogueFilterFields
                filters={draft}
                releases={releases}
                releaseStatus={releaseStatus}
                facets={facets}
                onChange={setDraft}
              />
              {releaseStatus === "error" && <ReleaseRetry onRetry={onRetryReleases} />}
              {legend && <div className="border-t border-border-default pt-4">{legend}</div>}
            </div>

            <div className="sticky bottom-0 -mx-5 mt-6 flex gap-2 border-t border-border-default bg-bg-elevated px-5 pb-[max(0.25rem,env(safe-area-inset-bottom))] pt-4">
              <button
                type="button"
                onClick={() => {
                  onChange({ ...filters, release: "", rarity: "", treatment: "" });
                  setOpen(false);
                }}
                className="min-h-11 flex-1 rounded-control border border-border-default px-4 text-sm font-medium text-text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => {
                  onChange(draft);
                  setOpen(false);
                }}
                className="min-h-11 flex-[1.4] rounded-control border border-accent-gold bg-accent-gold/10 px-4 text-sm font-semibold text-parchment focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal"
              >
                Apply filters
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function PrintCatalogueSortControl({
  value,
  onChange,
}: {
  value: PrintCatalogueSort;
  onChange: (value: PrintCatalogueSort) => void;
}) {
  return (
    <label className="flex min-w-0 items-center gap-2">
      <span className="mono hidden text-[10px] uppercase tracking-[0.14em] text-text-faint sm:inline">Sort</span>
      <select
        aria-label="Sort"
        value={value}
        onChange={(event) => onChange(event.target.value as PrintCatalogueSort)}
        className="min-h-11 max-w-[11.5rem] min-w-0 rounded-control border border-border-default bg-bg-surface px-2 text-xs text-text-primary focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal"
      >
        {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function CatalogueFilterFields({
  filters,
  releases,
  releaseStatus,
  facets,
  onChange,
}: {
  filters: PrintCatalogueFilters;
  releases: { value: string; label: string }[];
  releaseStatus: "loading" | "ready" | "error";
  facets: PrintCatalogueFacets;
  onChange: (next: PrintCatalogueFilters) => void;
}) {
  function set<K extends keyof PrintCatalogueFilters>(key: K, value: PrintCatalogueFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  const releaseOptions = releases.map((release) => {
    const suppliedName = release.label !== release.value ? release.label : undefined;
    const name = releaseDisplayName(release.value, suppliedName);
    return { value: release.value, label: name === "Release name unavailable" ? release.value : `${release.value} — ${name}` };
  });
  if (filters.release && !releaseOptions.some((release) => release.value === filters.release)) {
    releaseOptions.unshift({ value: filters.release, label: filters.release });
  }

  const treatmentOptions = facets.treatments.map((value) => ({ value, label: titleCase(value) }));
  if (filters.treatment && !treatmentOptions.some((option) => option.value === filters.treatment)) {
    treatmentOptions.unshift({ value: filters.treatment, label: titleCase(filters.treatment) });
  }

  const rarityGroups = rarityOptionGroups(facets.rarities);
  if (filters.rarity && !rarityGroups.some((group) => group.options.some((option) => option.value === filters.rarity))) {
    rarityGroups.push({ label: "Selected", options: [{ value: filters.rarity, label: filters.rarity }] });
  }

  return (
    <>
      <FilterSelect
        label="Release"
        value={filters.release}
        onSelect={(value) => set("release", value)}
        placeholder={releaseStatus === "loading" ? "Loading releases…" : "All releases"}
        options={releaseOptions}
      />
      <FilterSelect
        label="Rarity"
        accessibleName="Rarity or special print"
        value={filters.rarity}
        onSelect={(value) => set("rarity", value)}
        placeholder="All rarities"
        groups={rarityGroups}
      />
      <FilterSelect
        label="Treatment"
        value={filters.treatment}
        onSelect={(value) => set("treatment", value)}
        placeholder="All treatments"
        options={treatmentOptions}
      />
    </>
  );
}

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
  accessibleName?: string;
  value: string;
  onSelect: (value: string) => void;
  options?: { value: string; label: string }[];
  groups?: FilterOptionGroup[];
  placeholder: string;
}) {
  return (
    <label className="block min-w-0">
      <span className="mono mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-text-faint">{label}</span>
      <select
        aria-label={accessibleName ?? label}
        value={value}
        onChange={(event) => onSelect(event.target.value)}
        className="min-h-11 w-full min-w-0 rounded-control border border-border-default bg-bg-page px-2.5 text-xs text-text-primary focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal"
      >
        <option value="">{placeholder}</option>
        {options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        {groups?.map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

function ReleaseRetry({ onRetry }: { onRetry: () => void }) {
  return <button type="button" onClick={onRetry} className="mt-3 min-h-11 text-xs text-text-secondary underline">Retry releases</button>;
}

function FilterIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 5h14M5.5 10h9M8 15h4" />
    </svg>
  );
}

function titleCase(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value;
}

export interface FilterOptionGroup {
  label: string;
  options: { value: string; label: string }[];
}

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
