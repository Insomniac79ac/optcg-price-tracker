"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState } from "@/components/StateBlocks";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import {
  CatalogueToolbar,
  EMPTY_CATALOGUE_FILTERS,
  hasActiveFilters,
  type CatalogueFilters,
} from "@/components/ui/CatalogueToolbar";
import { CollectorCardTile } from "@/components/ui/CollectorCardTile";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  type CardCatalogueList,
  type CardCatalogueSort,
  fetchCardsCatalogue,
} from "@/lib/api";

const PAGE_SIZE = 24;
const SORT_VALUES: CardCatalogueSort[] = ["card_code", "name", "index_desc", "index_asc", "updated"];
const MAX_QUERY_LENGTH = 128;

function isSortValue(value: string): value is CardCatalogueSort {
  return (SORT_VALUES as string[]).includes(value);
}

/** Reads catalogue state (search/filters/sort/page) directly from the URL's
 * query string rather than component state (design brief Phase 7 - "shared
 * URLs must reproduce the same view", "browser back/forward must restore
 * state") - every value here is re-derived on each render from whatever
 * `searchParams` currently is, so a back/forward navigation or a pasted URL
 * naturally re-renders with the right filters with no extra sync code.
 * Unrecognized/out-of-range values (a bad `sort`, a negative `offset`) are
 * discarded rather than passed through, so a hand-edited or stale URL never
 * reaches the API as-is. */
function parseCatalogueState(searchParams: URLSearchParams): {
  filters: CatalogueFilters;
  offset: number;
} {
  const rawSort = searchParams.get("sort") ?? "";
  const rawOffset = Number(searchParams.get("offset") ?? "0");

  return {
    filters: {
      q: (searchParams.get("q") ?? "").slice(0, MAX_QUERY_LENGTH),
      set_code: searchParams.get("set_code") ?? "",
      rarity: searchParams.get("rarity") ?? "",
      language: searchParams.get("language") ?? "",
      variant: searchParams.get("variant") ?? "",
      sort: isSortValue(rawSort) ? rawSort : EMPTY_CATALOGUE_FILTERS.sort,
    },
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? Math.floor(rawOffset) : 0,
  };
}

function buildQueryString(filters: CatalogueFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.set_code) params.set("set_code", filters.set_code);
  if (filters.rarity) params.set("rarity", filters.rarity);
  if (filters.language) params.set("language", filters.language);
  if (filters.variant) params.set("variant", filters.variant);
  if (filters.sort !== EMPTY_CATALOGUE_FILTERS.sort) params.set("sort", filters.sort);
  if (offset > 0) params.set("offset", String(offset));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export default function CardsCataloguePage() {
  return (
    <Suspense fallback={<CardsCataloguePageFallback />}>
      <CardsCataloguePageInner />
    </Suspense>
  );
}

function CardsCataloguePageFallback() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader title="Cards" description="Browse the card catalogue and Market Index." />
        <CardGridSkeleton />
      </main>
    </div>
  );
}

function CardsCataloguePageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { filters, offset } = parseCatalogueState(searchParams);

  const [data, setData] = useState<CardCatalogueList | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const paramsKey = searchParams.toString();

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchCardsCatalogue({
      q: filters.q || undefined,
      set_code: filters.set_code || undefined,
      rarity: filters.rarity || undefined,
      language: filters.language || undefined,
      variant: filters.variant || undefined,
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
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  function navigate(nextFilters: CatalogueFilters, nextOffset: number) {
    router.push(`${pathname}${buildQueryString(nextFilters, nextOffset)}`);
  }

  function handleFiltersChange(nextFilters: CatalogueFilters) {
    navigate(nextFilters, 0);
  }

  function handleClear() {
    navigate(EMPTY_CATALOGUE_FILTERS, 0);
  }

  function handleOffsetChange(nextOffset: number) {
    navigate(filters, nextOffset);
  }

  const emptyFacets = { set_codes: [], rarities: [], languages: [], variants: [] };

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Cards"
          description="Browse the card catalogue - Market Index shown alongside each card."
        />

        <CatalogueToolbar
          filters={filters}
          facets={data?.facets ?? emptyFacets}
          onChange={handleFiltersChange}
          onClear={handleClear}
        />

        {status === "loading" && <CardGridSkeleton />}

        {status === "error" && (
          <ErrorState
            action={
              <button
                type="button"
                onClick={() => navigate(filters, offset)}
                className="rounded-control border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
              >
                Retry
              </button>
            }
          >
            Failed to load the card catalogue.
          </ErrorState>
        )}

        {status === "ready" && data && data.items.length === 0 && (
          <CollectorEmptyState
            title={hasActiveFilters(filters) ? "No cards match these filters" : "No cards yet"}
            action={
              hasActiveFilters(filters) && (
                <button
                  type="button"
                  onClick={handleClear}
                  className="rounded-control border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
                >
                  Clear filters
                </button>
              )
            }
          >
            {hasActiveFilters(filters)
              ? "Try a different search term or clear filters to see the full catalogue."
              : "The catalogue is empty right now."}
          </CollectorEmptyState>
        )}

        {status === "ready" && data && data.items.length > 0 && (
          <>
            <CardGrid>
              {data.items.map((card) => (
                <CollectorCardTile key={card.id} card={card} />
              ))}
            </CardGrid>
            <div className="mt-4">
              <PaginationControls
                offset={offset}
                limit={PAGE_SIZE}
                total={data.total}
                onOffsetChange={handleOffsetChange}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
