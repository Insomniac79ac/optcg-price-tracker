"use client";

import Link from "next/link";
import { releaseLabelEnglish } from "@/lib/releaseNames";
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
import { buildCatalogueQuery, catalogueParams, EMPTY_PRINT_FILTERS, hasActivePrintFilters, parseCatalogueState, resolveLegacyRelease, type PrintCatalogueFilters } from "@/lib/catalogueState";
import { toPrintUiModel, printsNeedingArtOrdinal, type PrintCatalogueList } from "@/lib/prints";
import { fetchReleases, releaseLabel, type ReleaseCatalogueList, type ReleaseCatalogueItem } from "@/lib/releases";
import styles from "./CardsAtlas.module.css";

type Seed = { query: string; data: PrintCatalogueList | null };
export default function PrintsCataloguePage({ initialReleases = null, seed }: { initialReleases?: ReleaseCatalogueList | null; seed?: Seed }) {
  return seed ? <CatalogueRoute initialReleases={initialReleases} seed={seed} /> : <Suspense fallback={<CatalogueFallback />}><CatalogueRoute initialReleases={initialReleases} seed={seed} /></Suspense>;
}
function CatalogueFallback() {
  return <><AppHeader /><main className={styles.main}><CardAtlasHeader query="" onSearch={() => {}} totalPrints={null} /><CardGridSkeleton count={24} /></main></>;
}
function CatalogueRoute({ initialReleases, seed }: { initialReleases: ReleaseCatalogueList | null; seed?: Seed }) {
  const searchParams = useSearchParams();
  const releaseResource = usePublicResource(fetchReleases, initialReleases);
  const { filters: rawFilters, offset } = parseCatalogueState(searchParams);
  // Resolve old shared product codes before issuing a membership request.
  if (rawFilters.legacySet && releaseResource.status === 'loading') return <CatalogueFallback />;
  const releases = releaseResource.data?.items ?? [];
  const filters = resolveLegacyRelease(rawFilters, releases);
  const query = buildCatalogueQuery(filters, offset);
  return <CatalogueView seed={seed} query={query} filters={filters} offset={offset} releases={releases} releaseStatus={releaseResource.status} retryReleases={releaseResource.retry} />;
}
const emptyFacets = { treatments: [], rarities: [], languages: [], verification_statuses: [] };
function CatalogueView({ seed, query, filters, offset, releases, releaseStatus, retryReleases }: {
  seed?: Seed; query: string; filters: PrintCatalogueFilters; offset: number; releases: ReleaseCatalogueItem[];
  releaseStatus: "loading" | "ready" | "error"; retryReleases: () => void;
}) {
  const pathname = usePathname();
  const { data, facets, status, appending, appendError, hasMore, sentinel, loadMore, save, retry } = useProgressiveCatalogue(query, catalogueParams(filters), offset, seed);
  const prints = useMemo(() => (data?.items ?? []).map(toPrintUiModel), [data]);
  const ordinalNeeded = useMemo(() => printsNeedingArtOrdinal(prints), [prints]);
  const total = status === "ready" && data ? data.total : null;
  const navigate = (next: PrintCatalogueFilters) => {
    const href = `${pathname}${buildCatalogueQuery(next)}`;
    if (href === `${pathname}${query}`) return;
    save();
    // A user changing filters after several batches should start at the new
    // results, not leave the sentinel visible at the old, now-clamped depth.
    // Back restoration is separate and never takes this navigation path.
    const results = document.getElementById("catalogue-results");
    if (results && results.getBoundingClientRect().top < 0) {
      results.scrollIntoView({ block: "start", behavior: "instant" });
    }
    // Next App Router integrates native history with useSearchParams. Only
    // committed user changes push; automatic appends never touch the URL.
    window.history.pushState(null, "", href);
  };
  const chooseRelease = (id: number | null) => navigate({ ...filters, releaseProductId: id, legacySet: "" });
  return <div className="min-h-screen">
    <AppHeader />
    <main className={styles.main}>
      <CardAtlasHeader query={filters.q} onSearch={(q) => navigate({ ...filters, q })} totalPrints={total} />
      {filters.releaseProductId && <section className="my-5"><h2 className="text-xl font-semibold">{releaseLabelEnglish(releases.find((r) => r.release_product_id === filters.releaseProductId)?.official_code, releases.find((r) => r.release_product_id === filters.releaseProductId)?.display_name)} card prices</h2><p className="mt-2 text-text-secondary">Compare the exact card variants from this release. A missing price is not a value of zero.</p><Link href={`/analytics?release_product_id=${filters.releaseProductId}`} className="mt-3 inline-flex min-h-11 items-center text-accent-gold">See this release’s market movement →</Link></section>}
      <ReleaseNavigation releases={releases} status={releaseStatus} selected={filters.releaseProductId}
        hrefFor={(id) => `${pathname}${buildCatalogueQuery({ ...filters, releaseProductId: id, legacySet: '' })}`}
        onSelect={chooseRelease} onRetry={retryReleases} />
      <div className={styles.catalogueLayout}>
        <PrintCatalogueToolbar releases={releases} filters={filters} facets={facets ?? emptyFacets} onChange={navigate} legend={<CatalogueLegend />} />
        <div id="catalogue-results" className={styles.catalogueContent}>
          <div className={styles.catalogueBar}>
            <div className={styles.catalogueMeta}><h2 className={styles.catalogueTitle}>Exact card variants</h2>
              {total !== null && <p className={styles.catalogueCount}>{total.toLocaleString()} {total === 1 ? 'entry' : 'entries'} in this view</p>}
            </div>
            <PrintCatalogueSortControl value={filters.sort} onChange={(sort) => navigate({ ...filters, sort })} />
          </div>
          {hasActivePrintFilters(filters) && <ActiveFilterChips filters={filters} releases={releases} onChange={navigate} />}
          {status === 'loading' && <CardGridSkeleton count={24} />}
          {status === 'error' && <ErrorState tone="collector" action={<button type="button" className={styles.retryLink} onClick={retry}>Retry catalogue</button>}>Card prices could not be loaded.</ErrorState>}
          {status === 'ready' && prints.length === 0 && <CollectorEmptyState title="No card variants found" action={<button type="button" className={styles.retryLink} onClick={() => navigate(EMPTY_PRINT_FILTERS)}>Clear all</button>}>Adjust the release, rarity, treatment or search to continue browsing.</CollectorEmptyState>}
          {status === 'ready' && prints.length > 0 && <>
            <CardGrid>{prints.map((print) => <PrintCardTile key={print.cardPrintId} print={print} showArtOrdinal={ordinalNeeded.has(print.cardPrintId)} />)}</CardGrid>
            <div className={styles.progress}>
              <p role="status" aria-live="polite">{appending ? 'Loading more card variants…' : appendError ? 'More card variants could not be loaded. Your cards are still here.' : hasMore ? `${prints.length} card variants loaded${offset ? ` from position ${offset + 1}` : ''}` : `All ${prints.length} card variants${offset ? ' from this starting position' : ' in this view'} loaded.`}</p>
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
    {chips.map((chip) => <button key={chip.key} type="button" onClick={chip.remove} aria-label={`Remove ${chip.label.toLowerCase()} filter ${chip.value}`} className={styles.activeChip}>{chip.label}: <strong>{chip.value}</strong><span aria-hidden="true">×</span></button>)}
    <button type="button" className={styles.clearAll} onClick={() => onChange(EMPTY_PRINT_FILTERS)}>Clear all</button>
  </div>;
}
