"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardAtlasHeader } from "@/components/ui/CardAtlasHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CatalogueLegend } from "@/components/ui/CatalogueLegend";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { facetLabel, PrintCatalogueSortControl, PrintCatalogueToolbar } from "@/components/ui/PrintCatalogueToolbar";
import { ReleaseNavigation } from "@/components/ui/ReleaseNavigation";
import { usePublicResource } from "@/hooks/usePublicResource";
import { useProgressiveCatalogue } from "@/hooks/useProgressiveCatalogue";
import { activeFilterCount, buildCatalogueQuery, catalogueParams, EMPTY_PRINT_FILTERS, hasActivePrintFilters, parseCatalogueState, resolveLegacyRelease, type PrintCatalogueFilters } from "@/lib/catalogueState";
import { toPrintUiModel, printsNeedingArtOrdinal } from "@/lib/prints";
import { fetchReleases, releaseLabel, type ReleaseCatalogueItem } from "@/lib/releases";
import styles from "./CardsAtlas.module.css";

export default function PrintsCataloguePage() {
  return <Suspense fallback={<CatalogueFallback />}><CatalogueRoute /></Suspense>;
}
function CatalogueFallback() {
  return <><AppHeader /><main className={styles.main}><CardAtlasHeader query="" onSearch={() => {}} totalPrints={null} /><CardGridSkeleton count={24} /></main></>;
}
function CatalogueRoute() {
  const searchParams = useSearchParams();
  const releaseResource = usePublicResource(fetchReleases);
  const { filters: rawFilters, offset } = parseCatalogueState(searchParams);
  // Resolve old shared product codes before issuing a membership request.
  if (rawFilters.legacySet && releaseResource.status === 'loading') return <CatalogueFallback />;
  const releases = releaseResource.data?.items ?? [];
  const filters = resolveLegacyRelease(rawFilters, releases);
  const query = buildCatalogueQuery(filters, offset);
  return <CatalogueView key={query} query={query} filters={filters} offset={offset} releases={releases} releaseStatus={releaseResource.status} retryReleases={releaseResource.retry} />;
}
const emptyFacets = { treatments: [], rarities: [], languages: [], verification_statuses: [] };
function CatalogueView({ query, filters, offset, releases, releaseStatus, retryReleases }: {
  query: string; filters: PrintCatalogueFilters; offset: number; releases: ReleaseCatalogueItem[];
  releaseStatus: "loading" | "ready" | "error"; retryReleases: () => void;
}) {
  const pathname = usePathname();
  const { data, status, appending, appendError, hasMore, sentinel, loadMore, save, retry } = useProgressiveCatalogue(query, catalogueParams(filters), offset);
  const prints = useMemo(() => (data?.items ?? []).map(toPrintUiModel), [data]);
  const ordinalNeeded = useMemo(() => printsNeedingArtOrdinal(prints), [prints]);
  const total = status === "ready" && data ? data.total : null;
  const navigate = (next: PrintCatalogueFilters) => {
    const href = `${pathname}${buildCatalogueQuery(next)}`;
    if (href === `${pathname}${query}`) return;
    save();
    // Next App Router integrates native history with useSearchParams. Only
    // committed user changes push; automatic appends never touch the URL.
    window.history.pushState(null, "", href);
  };
  const chooseRelease = (id: number | null) => navigate({ ...filters, releaseProductId: id, legacySet: "" });
  return <div className="min-h-screen">
    <AppHeader />
    <main className={styles.main}>
      <CardAtlasHeader query={filters.q} onSearch={(q) => navigate({ ...filters, q })} totalPrints={total} />
      <ReleaseNavigation releases={releases} status={releaseStatus} selected={filters.releaseProductId}
        hrefFor={(id) => `${pathname}${buildCatalogueQuery({ ...filters, releaseProductId: id, legacySet: '' })}`}
        onSelect={chooseRelease} onRetry={retryReleases} />
      <div className={styles.catalogueLayout}>
        <PrintCatalogueToolbar filters={filters} facets={data?.facets ?? emptyFacets} onChange={navigate} legend={<CatalogueLegend />} />
        <div className={styles.catalogueContent}>
          <div className={styles.catalogueBar}>
            <div className={styles.catalogueMeta}><h2 className={styles.catalogueTitle}>Exact printings</h2>
              {total !== null && <p className={styles.catalogueCount}>{total.toLocaleString()} {total === 1 ? 'entry' : 'entries'} in this view</p>}
            </div>
            <PrintCatalogueSortControl value={filters.sort} onChange={(sort) => navigate({ ...filters, sort })} />
          </div>
          {hasActivePrintFilters(filters) && <ActiveFilterChips filters={filters} releases={releases} onChange={navigate} />}
          {status === 'loading' && <CardGridSkeleton count={24} />}
          {status === 'error' && <ErrorState tone="collector" action={<button type="button" className={styles.retryLink} onClick={retry}>Retry catalogue</button>}>The Card Atlas could not be loaded.</ErrorState>}
          {status === 'ready' && prints.length === 0 && <CollectorEmptyState title="No printings found" action={<button type="button" className={styles.retryLink} onClick={() => navigate(EMPTY_PRINT_FILTERS)}>Clear all</button>}>Adjust the release, rarity, treatment or search to continue browsing.</CollectorEmptyState>}
          {status === 'ready' && prints.length > 0 && <>
            <CardGrid>{prints.map((print) => <PrintCardTile key={print.cardPrintId} print={print} showArtOrdinal={ordinalNeeded.has(print.cardPrintId)} />)}</CardGrid>
            <div className={styles.progress}>
              <p role="status" aria-live="polite">{appending ? 'Loading more printings…' : appendError ? 'More printings could not be loaded. Your cards are still here.' : hasMore ? `${prints.length} printings loaded${offset ? ` from position ${offset + 1}` : ''}` : `All ${prints.length} printings${offset ? ' from this starting position' : ' in this view'} loaded.`}</p>
              {hasMore && <button type="button" disabled={appending} onClick={() => void loadMore()}>{appendError ? 'Retry load more' : 'Load more'}</button>}
              <div ref={sentinel} aria-hidden="true" data-catalogue-sentinel />
            </div>
          </>}
        </div>
      </div>
    </main>
  </div>;
}
function ActiveFilterChips({ filters, releases, onChange }: {
  filters: PrintCatalogueFilters; releases: ReleaseCatalogueItem[]; onChange: (next: PrintCatalogueFilters) => void;
}) {
  const release = releases.find((r) => r.release_product_id === filters.releaseProductId);
  const chips = [
    ...(filters.releaseProductId || filters.legacySet ? [{ key: 'release', label: 'Release', value: release ? releaseLabel(release) : filters.legacySet || 'Selected release', remove: () => onChange({ ...filters, releaseProductId: null, legacySet: '' }) }] : []),
    ...filters.rarities.map((value) => ({ key: `rarity:${value}`, label: 'Rarity', value: facetLabel(value), remove: () => onChange({ ...filters, rarities: filters.rarities.filter((v) => v !== value) }) })),
    ...filters.treatments.map((value) => ({ key: `treatment:${value}`, label: 'Treatment', value, remove: () => onChange({ ...filters, treatments: filters.treatments.filter((v) => v !== value) }) })),
    ...(filters.q ? [{ key: 'q', label: 'Search', value: filters.q, remove: () => onChange({ ...filters, q: '' }) }] : []),
  ];
  return <div className={styles.activeRow} aria-label="Active catalogue filters">
    <span className="text-xs text-text-muted">{activeFilterCount(filters)} active</span>
    {chips.map((chip) => <button key={chip.key} type="button" onClick={chip.remove} aria-label={`Remove ${chip.label.toLowerCase()} filter ${chip.value}`} className={styles.activeChip}>{chip.label}: <strong>{chip.value}</strong><span aria-hidden="true">×</span></button>)}
    <button type="button" className={styles.clearAll} onClick={() => onChange(EMPTY_PRINT_FILTERS)}>Clear all</button>
  </div>;
}
