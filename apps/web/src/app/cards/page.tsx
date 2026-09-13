"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState } from "@/components/StateBlocks";
import { CardAtlasHeader } from "@/components/ui/CardAtlasHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CatalogueLegend } from "@/components/ui/CatalogueLegend";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import {
  EMPTY_PRINT_FILTERS,
  hasActivePrintFilters,
  PrintCatalogueSortControl,
  PrintCatalogueToolbar,
  type PrintCatalogueFilters,
} from "@/components/ui/PrintCatalogueToolbar";
import { fetchMarketFilters, type MarketFilterOption } from "@/lib/marketAnalytics";
import {
  fetchPrintCatalogue,
  PRINT_SORT_VALUES,
  type PrintCatalogueList,
  type PrintCatalogueSort,
  toPrintUiModel,
  printsNeedingArtOrdinal,
} from "@/lib/prints";
import { releaseDisplayName } from "@/lib/releaseNames";

import styles from "./CardsAtlas.module.css";

const PAGE_SIZE = 24;
const MAX_QUERY_LENGTH = 128;

function isSortValue(value: string): value is PrintCatalogueSort {
  return (PRINT_SORT_VALUES as string[]).includes(value);
}

/** The URL is the committed catalogue state. */
function parseCatalogueState(searchParams: URLSearchParams): {
  filters: PrintCatalogueFilters;
  offset: number;
} {
  const rawSort = searchParams.get("sort") ?? "";
  const rawOffset = Number(searchParams.get("offset") ?? "0");

  return {
    filters: {
      q: (searchParams.get("q") ?? "").slice(0, MAX_QUERY_LENGTH),
      treatment: searchParams.get("treatment") ?? "",
      release: searchParams.get("set") ?? "",
      rarity: searchParams.get("rarity") ?? "",
      sort: isSortValue(rawSort) ? rawSort : EMPTY_PRINT_FILTERS.sort,
    },
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? Math.floor(rawOffset) : 0,
  };
}

function buildQueryString(filters: PrintCatalogueFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.release) params.set("set", filters.release);
  if (filters.q) params.set("q", filters.q);
  if (filters.treatment) params.set("treatment", filters.treatment);
  if (filters.rarity) params.set("rarity", filters.rarity);
  if (filters.sort !== EMPTY_PRINT_FILTERS.sort) params.set("sort", filters.sort);
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export default function PrintsCataloguePage() {
  return (
    <Suspense fallback={<PrintsCataloguePageFallback />}>
      <PrintsCataloguePageInner />
    </Suspense>
  );
}

function PrintsCataloguePageFallback() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className={styles.main}>
        <CardAtlasHeader query="" onSearch={() => {}} totalPrints={null} />
        <ReleaseNavigation
          releases={[]}
          status="loading"
          selected=""
          hrefFor={() => "/cards"}
          onSelect={() => {}}
          onRetry={() => {}}
        />
        <div className={styles.catalogueLayout}>
          <div className="hidden lg:block" aria-hidden="true" />
          <div className={styles.catalogueContent}>
            <CatalogueHeading total={null} sort={EMPTY_PRINT_FILTERS.sort} onSort={() => {}} />
            <CardGridSkeleton />
          </div>
        </div>
      </main>
    </div>
  );
}

/** Print-centric catalogue backed by GET /prints. Each tile is one
 * card_print and carries only that printing's identity and prices. */
function PrintsCataloguePageInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { filters, offset } = parseCatalogueState(searchParams);

  const [data, setData] = useState<PrintCatalogueList | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [catalogueAttempt, setCatalogueAttempt] = useState(0);
  const [releases, setReleases] = useState<MarketFilterOption[]>([]);
  const [releaseStatus, setReleaseStatus] = useState<"loading" | "ready" | "error">("loading");
  const [releaseAttempt, setReleaseAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchMarketFilters()
      .then((result) => {
        if (cancelled) return;
        // Membership stays exactly the vocabulary the server published.
        setReleases([...result.sets].sort((a, b) =>
          a.value.localeCompare(b.value, "en", { numeric: true }) ||
          (a.value < b.value ? -1 : a.value > b.value ? 1 : 0),
        ));
        setReleaseStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setReleaseStatus("error");
      });
    return () => { cancelled = true; };
  }, [releaseAttempt]);

  const paramsKey = searchParams.toString();

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");
    fetchPrintCatalogue({
      set: filters.release || undefined,
      q: filters.q || undefined,
      treatment: filters.treatment || undefined,
      rarity: filters.rarity || undefined,
      sort: filters.sort,
      limit: PAGE_SIZE,
      offset,
    })
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey, catalogueAttempt]);

  const prints = useMemo(() => (data?.items ?? []).map(toPrintUiModel), [data]);
  const ordinalNeeded = useMemo(() => printsNeedingArtOrdinal(prints), [prints]);

  /** Same-route native history keeps useSearchParams, shared URLs and browser
   * history in sync on this statically prerendered route. */
  function navigate(nextFilters: PrintCatalogueFilters, nextOffset: number) {
    window.history.pushState(null, "", `${pathname}${buildQueryString(nextFilters, nextOffset)}`);
    window.scrollTo({ top: 0 });
  }

  const emptyFacets = {
    treatments: [],
    rarities: [],
    languages: [],
    verification_statuses: [],
  };
  const total = status === "ready" && data ? data.total : null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className={styles.main}>
        <CardAtlasHeader
          query={filters.q}
          onSearch={(query) => navigate({ ...filters, q: query }, 0)}
          totalPrints={total}
        />

        <ReleaseNavigation
          releases={releases}
          status={releaseStatus}
          selected={filters.release}
          hrefFor={(release) => `${pathname}${buildQueryString({ ...filters, release }, 0)}`}
          onSelect={(release) => navigate({ ...filters, release }, 0)}
          onRetry={() => {
            setReleaseStatus("loading");
            setReleaseAttempt((attempt) => attempt + 1);
          }}
        />

        <div className={styles.catalogueLayout}>
          <PrintCatalogueToolbar
            releases={releases}
            releaseStatus={releaseStatus}
            onRetryReleases={() => {
              setReleaseStatus("loading");
              setReleaseAttempt((attempt) => attempt + 1);
            }}
            filters={filters}
            facets={data?.facets ?? emptyFacets}
            onChange={(next) => navigate(next, 0)}
            legend={<CatalogueLegend />}
          />

          <div className={styles.catalogueContent}>
            <CatalogueHeading
              total={total}
              sort={filters.sort}
              onSort={(sort) => navigate({ ...filters, sort }, 0)}
            />

            {hasActivePrintFilters(filters) && (
              <ActiveFilterChips
                filters={filters}
                onChange={(next) => navigate(next, 0)}
                onClear={() => navigate(EMPTY_PRINT_FILTERS, 0)}
              />
            )}

            {status === "loading" && <CardGridSkeleton />}

            {status === "error" && (
              <div className={styles.stateBlock}>
                <ErrorState
                  tone="collector"
                  action={
                    <button
                      type="button"
                      onClick={() => {
                        setStatus("loading");
                        setCatalogueAttempt((attempt) => attempt + 1);
                      }}
                      className="min-h-11 rounded-control border border-border-default px-4 text-xs font-medium text-text-secondary hover:text-text-primary"
                    >
                      Retry catalogue
                    </button>
                  }
                >
                  The Card Atlas could not be loaded.
                </ErrorState>
              </div>
            )}

            {status === "ready" && prints.length === 0 && (
              <div className={styles.stateBlock}>
                <CollectorEmptyState
                  title={hasActivePrintFilters(filters) ? "No printings found in this charted view" : "No cards yet"}
                  action={hasActivePrintFilters(filters) && (
                    <button
                      type="button"
                      onClick={() => navigate(EMPTY_PRINT_FILTERS, 0)}
                      className="min-h-11 rounded-control border border-border-default px-4 text-xs font-medium text-text-secondary hover:text-text-primary"
                    >
                      Clear filters
                    </button>
                  )}
                >
                  {hasActivePrintFilters(filters)
                    ? "Adjust the release, rarity, treatment or search to continue browsing."
                    : "The catalogue is empty right now."}
                </CollectorEmptyState>
              </div>
            )}

            {status === "ready" && data && prints.length > 0 && (
              <>
                <CardGrid>
                  {prints.map((print) => (
                    <PrintCardTile
                      key={print.cardPrintId}
                      print={print}
                      showArtOrdinal={ordinalNeeded.has(print.cardPrintId)}
                    />
                  ))}
                </CardGrid>
                <div className="mt-8">
                  <PaginationControls
                    offset={offset}
                    limit={PAGE_SIZE}
                    total={data.total}
                    onOffsetChange={(nextOffset) => navigate(filters, nextOffset)}
                    variant="catalogue"
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function CatalogueHeading({
  total,
  sort,
  onSort,
}: {
  total: number | null;
  sort: PrintCatalogueSort;
  onSort: (sort: PrintCatalogueSort) => void;
}) {
  return (
    <div className={styles.catalogueBar}>
      <div className={styles.catalogueMeta}>
        <h2 className={styles.catalogueTitle}>Exact printings</h2>
        {total !== null && (
          <p className={styles.catalogueCount}>
            {total.toLocaleString()} {total === 1 ? "entry" : "entries"} in this view
          </p>
        )}
      </div>
      <div className={styles.sortRow}>
        <PrintCatalogueSortControl value={sort} onChange={onSort} />
      </div>
    </div>
  );
}

function ReleaseNavigation({
  releases,
  status,
  selected,
  hrefFor,
  onSelect,
  onRetry,
}: {
  releases: MarketFilterOption[];
  status: "loading" | "ready" | "error";
  selected: string;
  hrefFor: (release: string) => string;
  onSelect: (release: string) => void;
  onRetry: () => void;
}) {
  const selectedRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (status !== "ready") return;
    selectedRef.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [selected, status]);

  function selectRelease(event: MouseEvent<HTMLAnchorElement>, release: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onSelect(release);
  }

  return (
    <section className={styles.releaseSection} aria-labelledby="release-browse-title">
      <div className={styles.releaseHeadingRow}>
        <div>
          <p className={styles.sectionLabel}>Chart a course</p>
          <h2 id="release-browse-title" className={styles.sectionTitle}>Browse by release</h2>
        </div>
        <p className={styles.releaseHint}>Scroll to explore the official catalogue</p>
      </div>

      <nav className={styles.releaseScroller} aria-label="Browse releases">
        <div className={styles.releaseList}>
          <a
            ref={selected === "" ? selectedRef : undefined}
            href={hrefFor("")}
            aria-label="All releases — complete exact-print catalogue"
            aria-current={selected === "" ? "page" : undefined}
            onClick={(event) => selectRelease(event, "")}
            className={`${styles.releaseCard} ${selected === "" ? styles.releaseCardSelected : ""}`}
          >
            <span className={styles.releaseCode}>ALL RELEASES</span>
            <span className={styles.releaseName}>Complete exact-print catalogue</span>
          </a>

          {releases.map((release) => {
            const selectedRelease = selected === release.value;
            const suppliedName = release.label !== release.value ? release.label : undefined;
            const displayName = releaseDisplayName(release.value, suppliedName);
            return (
              <a
                ref={selectedRelease ? selectedRef : undefined}
                key={release.value}
                href={hrefFor(release.value)}
                aria-label={`${release.value} ${displayName}`}
                aria-current={selectedRelease ? "page" : undefined}
                onClick={(event) => selectRelease(event, release.value)}
                className={`${styles.releaseCard} ${selectedRelease ? styles.releaseCardSelected : ""}`}
              >
                <span className={styles.releaseCode}>{release.value}</span>
                <span className={styles.releaseName}>{displayName}</span>
              </a>
            );
          })}
        </div>
      </nav>

      {status === "loading" && releases.length === 0 && <div className={styles.releaseLoading}>Loading release destinations…</div>}
      {status === "error" && releases.length === 0 && (
        <button type="button" onClick={onRetry} className={styles.retryLink}>Retry release destinations</button>
      )}
    </section>
  );
}

function ActiveFilterChips({
  filters,
  onChange,
  onClear,
}: {
  filters: PrintCatalogueFilters;
  onChange: (next: PrintCatalogueFilters) => void;
  onClear: () => void;
}) {
  const chips = [
    filters.release && {
      key: "release",
      label: "Release",
      value: filters.release,
      remove: () => onChange({ ...filters, release: "" }),
    },
    filters.rarity && {
      key: "rarity",
      label: "Rarity",
      value: filters.rarity,
      remove: () => onChange({ ...filters, rarity: "" }),
    },
    filters.treatment && {
      key: "treatment",
      label: "Treatment",
      value: filters.treatment[0].toUpperCase() + filters.treatment.slice(1),
      remove: () => onChange({ ...filters, treatment: "" }),
    },
    filters.q && {
      key: "query",
      label: "Search",
      value: `“${filters.q}”`,
      remove: () => onChange({ ...filters, q: "" }),
    },
  ].filter(Boolean) as { key: string; label: string; value: string; remove: () => void }[];

  return (
    <div className={styles.activeRow} aria-label="Active catalogue filters">
      {chips.map((chip) => (
        <button key={chip.key} type="button" onClick={chip.remove} aria-label={`Remove ${chip.label.toLowerCase()} filter ${chip.value}`} className={styles.activeChip}>
          {chip.label}: <strong>{chip.value}</strong>
          <span className={styles.chipRemove} aria-hidden="true">×</span>
        </button>
      ))}
      <button type="button" onClick={onClear} className={styles.clearAll}>Clear all</button>
    </div>
  );
}
