"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";
import { classifyRarityToken } from "@/lib/terminology";
import type { PrintCatalogueFacets, PrintCatalogueSort } from "@/lib/prints";
import { collectorRefinementCount, EMPTY_PRINT_FILTERS, type PrintCatalogueFilters } from "@/lib/catalogueState";
import { CatalogueDialog } from "./CatalogueDialog";
import { CollectorMultiSelect } from "./CollectorMultiSelect";
export { EMPTY_PRINT_FILTERS, hasActivePrintFilters, type PrintCatalogueFilters } from "@/lib/catalogueState";

const MOBILE_QUERY = "(max-width: 63.999rem)";
const SORT_OPTIONS: { value: PrintCatalogueSort; label: string }[] = [
  { value: "card_code", label: "Card code" }, { value: "name", label: "Name" },
  { value: "index_desc", label: "Market Index ↓" }, { value: "index_asc", label: "Market Index ↑" },
  { value: "created_desc", label: "Recently added" }, { value: "updated", label: "Recently updated" },
];
function subscribeToMobile(onChange: () => void) {
  const media = window.matchMedia(MOBILE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function PrintCatalogueToolbar({ filters, facets, onChange, legend }: {
  filters: PrintCatalogueFilters; facets: PrintCatalogueFacets;
  onChange: (next: PrintCatalogueFilters) => void; legend?: ReactNode;
}) {
  const mobile = useSyncExternalStore(subscribeToMobile, () => window.matchMedia(MOBILE_QUERY).matches, () => false);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(filters);
  const count = collectorRefinementCount(filters);
  if (!mobile) return (
    <aside className="sticky top-[calc(var(--header-h)+1rem)] rounded-panel border border-border-default bg-bg-surface p-4" aria-labelledby="catalogue-filters-title">
      <h2 id="catalogue-filters-title" className="font-display text-lg font-semibold">Collector filters{count > 0 ? ` · ${count}` : ""}</h2>
      <CatalogueFilterFields filters={filters} facets={facets} onChange={onChange} />
      <div className="mt-4 border-t border-border-muted pt-4">{legend}</div>
      {count > 0 && <button type="button" className="mt-2 min-h-11 text-xs underline" onClick={() => onChange({ ...filters, rarities: [], treatments: [] })}>Clear collector filters</button>}
    </aside>
  );
  return <>
    <div className="mb-3 flex items-center justify-between gap-3">
      <button type="button" onClick={() => { setDraft(filters); setOpen(true); }} aria-haspopup="dialog" aria-expanded={open} className="min-h-11 rounded-control border border-accent-gold/70 bg-bg-elevated px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-accent-teal">Filters{count > 0 ? ` · ${count}` : ""}</button>
      {legend}
    </div>
    {open && <CatalogueDialog label="Filters" sheet onClose={() => setOpen(false)}>
      <CatalogueFilterFields filters={draft} facets={facets} onChange={setDraft} />
      <div className="sticky bottom-0 mt-5 flex gap-3 border-t border-border-default bg-bg-elevated pt-4">
        <button type="button" onClick={() => setDraft(EMPTY_PRINT_FILTERS)} className="min-h-11 flex-1 rounded-control border border-border-default">Clear all</button>
        <button type="button" onClick={() => { onChange(draft); setOpen(false); }} className="min-h-11 flex-1 rounded-control border border-accent-gold text-parchment">Apply filters</button>
      </div>
    </CatalogueDialog>}
  </>;
}

export function PrintCatalogueSortControl({ value, onChange }: { value: PrintCatalogueSort; onChange: (value: PrintCatalogueSort) => void }) {
  return <label className="flex min-w-0 items-center gap-2">
    <span className="sr-only">Sort</span>
    <select value={value} onChange={(event) => onChange(event.target.value as PrintCatalogueSort)} className="min-h-11 max-w-[11.5rem] min-w-0 rounded-control border border-border-default bg-bg-surface px-2 text-xs text-text-primary focus-visible:outline-2 focus-visible:outline-accent-teal">
      {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </label>;
}

export function facetLabel(value: string): string {
  const facts = classifyRarityToken(value);
  return facts.rarity?.label ?? facts.specialPrint?.label ?? value;
}
function CatalogueFilterFields({ filters, facets, onChange }: {
  filters: PrintCatalogueFilters; facets: PrintCatalogueFacets; onChange: (next: PrintCatalogueFilters) => void;
}) {
  return <div className="mt-4 flex flex-col gap-3">
    <CollectorMultiSelect label="Rarity" options={facets.rarities} selected={filters.rarities} optionLabel={facetLabel}
      onChange={(rarities) => onChange({ ...filters, rarities })} />
    <CollectorMultiSelect label="Treatment" options={facets.treatments} selected={filters.treatments}
      onChange={(treatments) => onChange({ ...filters, treatments })} />
  </div>;
}
