"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState } from "@/components/StateBlocks";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import {
  EMPTY_PRINT_FILTERS,
  hasActivePrintFilters,
  PrintCatalogueToolbar,
  type PrintCatalogueFilters,
} from "@/components/ui/PrintCatalogueToolbar";
import {
  fetchPrintCatalogue,
  PRINT_SORT_VALUES,
  type PrintCatalogueList,
  type PrintCatalogueSort,
  toPrintUiModel,
} from "@/lib/prints";

const PAGE_SIZE = 24;
const MAX_QUERY_LENGTH = 128;

function isSortValue(value: string): value is PrintCatalogueSort {
  return (PRINT_SORT_VALUES as string[]).includes(value);
}

/** Reads catalogue state (search/filters/sort/page) directly from the URL's
 * query string rather than component state, so a shared URL reproduces the
 * same view and browser back/forward restores it with no extra sync code.
 * Unrecognized/out-of-range values (a bad `sort`, a negative `offset`) are
 * discarded rather than passed through. */
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
      rarity: searchParams.get("rarity") ?? "",
      sort: isSortValue(rawSort) ? rawSort : EMPTY_PRINT_FILTERS.sort,
    },
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? Math.floor(rawOffset) : 0,
  };
}

function buildQueryString(filters: PrintCatalogueFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.treatment) params.set("treatment", filters.treatment);
  if (filters.rarity) params.set("rarity", filters.rarity);
  if (filters.sort !== EMPTY_PRINT_FILTERS.sort) params.set("sort", filters.sort);
  if (offset > 0) params.set("offset", String(offset));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

const PAGE_DESCRIPTION =
  "Every printing is its own card here — base and parallel are collected separately.";

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
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader title="Cards" description={PAGE_DESCRIPTION} />
        <CardGridSkeleton />
      </main>
    </div>
  );
}

/** The public card catalogue, print-centric end to end.
 *
 * Backed by `GET /prints` (see src/lib/prints.ts), never the legacy
 * card_id-keyed `/cards/catalogue`: each tile is exactly one `card_print`, so
 * sibling prints that bridge through the same legacy `cards` row - Sanji
 * OP01-013 base and parallel, for instance - are shown and priced separately
 * rather than merged into one row.
 */
function PrintsCataloguePageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { filters, offset } = parseCatalogueState(searchParams);

  const [data, setData] = useState<PrintCatalogueList | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const paramsKey = searchParams.toString();

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchPrintCatalogue({
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
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  const prints = useMemo(() => (data?.items ?? []).map(toPrintUiModel), [data]);

  function navigate(nextFilters: PrintCatalogueFilters, nextOffset: number) {
    router.push(`${pathname}${buildQueryString(nextFilters, nextOffset)}`);
  }

  const emptyFacets = {
    treatments: [],
    rarities: [],
    languages: [],
    verification_statuses: [],
  };

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader title="Cards" description={PAGE_DESCRIPTION} />

        <PrintCatalogueToolbar
          filters={filters}
          facets={data?.facets ?? emptyFacets}
          onChange={(next) => navigate(next, 0)}
          onClear={() => navigate(EMPTY_PRINT_FILTERS, 0)}
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

        {status === "ready" && prints.length === 0 && (
          <CollectorEmptyState
            title={
              hasActivePrintFilters(filters) ? "No cards match these filters" : "No cards yet"
            }
            action={
              hasActivePrintFilters(filters) && (
                <button
                  type="button"
                  onClick={() => navigate(EMPTY_PRINT_FILTERS, 0)}
                  className="rounded-control border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
                >
                  Clear filters
                </button>
              )
            }
          >
            {hasActivePrintFilters(filters)
              ? "Try a different search term or clear filters to see the full catalogue."
              : "The catalogue is empty right now."}
          </CollectorEmptyState>
        )}

        {status === "ready" && data && prints.length > 0 && (
          <>
            <CardGrid>
              {prints.map((print) => (
                <PrintCardTile key={print.cardPrintId} print={print} />
              ))}
            </CardGrid>
            <div className="mt-4">
              <PaginationControls
                offset={offset}
                limit={PAGE_SIZE}
                total={data.total}
                onOffsetChange={(nextOffset) => navigate(filters, nextOffset)}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
