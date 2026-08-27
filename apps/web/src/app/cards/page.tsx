"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState } from "@/components/StateBlocks";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CatalogueIntro } from "@/components/ui/CatalogueIntro";
import { CatalogueLegend } from "@/components/ui/CatalogueLegend";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
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
  type PrintUiModel,
  toPrintUiModel,
  printsNeedingArtOrdinal,
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
      <main className="mx-auto max-w-7xl px-4 py-4">
        {/* Same intro as the real page so the Suspense fallback doesn't
            reflow the whole top of the catalogue once the URL is readable -
            with no count and no card fan, because there is no response to
            draw either from yet. */}
        <CatalogueIntro query="" onSearch={() => {}} totalPrints={null} filtered={false} />
        <div className="mt-4">
          <CardGridSkeleton />
        </div>
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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { filters, offset } = parseCatalogueState(searchParams);

  const [data, setData] = useState<PrintCatalogueList | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  /** The pool the intro's card fan draws from, latched to the first response
   * that actually returned prints and never replaced.
   *
   * The fan is meant to represent the catalogue, not the visitor's current
   * view, so it must not re-pick every time a treatment, rarity or sort
   * changes the response - watching `data` would do exactly that. Latching
   * costs no extra request: it keeps the first page of prints the page had
   * already fetched for its own grid.
   *
   * An empty response is deliberately not latched. A visitor who lands on a
   * search that matches nothing would otherwise pin the fan to "no cards" for
   * the rest of the session. */
  const [heroPool, setHeroPool] = useState<PrintUiModel[] | null>(null);

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
        const loaded = result.items.map(toPrintUiModel);
        setHeroPool((latched) => (latched && latched.length > 0 ? latched : loaded));
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
  // Scoped to the prints on screen together - see printsNeedingArtOrdinal.
  const ordinalNeeded = useMemo(() => printsNeedingArtOrdinal(prints), [prints]);

  /** Commits catalogue state to the URL - the only state this page keeps, since
   * everything above reads back out of `useSearchParams()`.
   *
   * Deliberately the native History API rather than `router.push`, which the
   * App Router silently drops on this route. /cards is statically prerendered,
   * and any *visible* `<Link href="/cards">` prefetches that static entry into
   * the client router cache - the header's own public nav does exactly that
   * from `md` up. Once it is cached, a `router.push` issued from a URL that
   * already carries search params (`?q=...`) is answered with a replaceState
   * back to the URL you are already on: the address bar never changes, so
   * `useSearchParams()` never changes, so the grid never refetches. Below `md`
   * the identical push works, because those links are `display:none`, never
   * intersect, and so never prefetch /cards.
   *
   * Reproduced against a production build at 767px (works) and 769px (does
   * not). It was not specific to clearing: submitting a second search from a
   * `?q=` URL and the toolbar's own "Clear all" were dead the same way.
   *
   * Next.js supports the native History API for precisely this case - a
   * same-route search-param update - and keeps `useSearchParams()`, its own
   * router state and the back/forward buttons in sync with it. The explicit
   * scroll-to-top just preserves `router.push`'s default, which pagination
   * relies on. */
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

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-4">
        <CatalogueIntro
          query={filters.q}
          onSearch={(q) => navigate({ ...filters, q }, 0)}
          // Only ever the live `total` for the query in the URL - null (and
          // therefore nothing rendered) while loading or after a failure.
          totalPrints={status === "ready" && data ? data.total : null}
          filtered={hasActivePrintFilters(filters)}
          // The latched catalogue pool, not the filtered grid below: the
          // fan picks three of these for today and keeps them while the
          // visitor searches, filters and sorts.
          heroPrints={heroPool ?? []}
        />

        {/* Straight from the intro into the real controls. The compass
            divider that used to sit here read as a standalone ornament and
            cost ~60px before the first card; the intro panel's own edge is
            transition enough. */}
        <div className="mt-4 flex flex-col gap-3">
          <PrintCatalogueToolbar
            filters={filters}
            facets={data?.facets ?? emptyFacets}
            onChange={(next) => navigate(next, 0)}
            onClear={() => navigate(EMPTY_PRINT_FILTERS, 0)}
          />
          {/* The terminology key. Sits under the filters rather than in them:
              it explains the badges on the tiles below, not the controls
              above. Tap/click/keyboard - never hover-only. */}
          <CatalogueLegend />
        </div>

        {status === "loading" && <CardGridSkeleton />}

        {status === "error" && (
          <ErrorState
            tone="collector"
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
                <PrintCardTile
                  key={print.cardPrintId}
                  print={print}
                  showArtOrdinal={ordinalNeeded.has(print.cardPrintId)}
                />
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
