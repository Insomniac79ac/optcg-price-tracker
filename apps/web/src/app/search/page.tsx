"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { SearchTypeBadge } from "@/components/SearchTypeBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  SEARCH_TYPES,
  type SearchResult,
  type SearchSuggestion,
  type SearchSummary,
  type SearchType,
  fetchSearch,
  fetchSearchSuggestions,
} from "@/lib/api";

const MAX_REDIRECT_QUERY_LENGTH = 128;

/** /cards is now the primary public catalogue (design brief Phase 8) -
 * "/search?q=<query> redirects to /cards?q=<query>", so a *submitted*
 * search (a non-empty `q`) whose type scope includes cards (no `types`
 * param, or `types` naming only "cards") redirects there instead of
 * rendering this page's old table-style results. A bare /search visit with
 * no `q` yet (e.g. the dashboard's "Search cards, collection, wishlist,
 * notes, signals…" shortcut, opened before the visitor has typed anything)
 * is deliberately NOT redirected - it still shows this page's suggestion
 * list and type chips, since that multi-type command-center capability
 * (collection/wishlist/grading/notes/activity/signals/opportunities/reports
 * - none of which /cards can serve) has no other entry point once a query
 * is actually about one of those types. `types` naming any non-"cards" type
 * also skips the redirect for the same reason. Only `q` is translated onward
 * - `types`/`limit`/`offset` aren't part of /cards' contract, so they're
 * safely dropped rather than passed through. This can never loop: the
 * target is a different route (/cards), which never redirects back to
 * /search. */
function shouldRedirectToCards(searchParams: URLSearchParams): boolean {
  const q = (searchParams.get("q") ?? "").trim();
  if (!q) return false;

  const types = searchParams.get("types");
  if (!types) return true;
  const requested = types
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return requested.length === 0 || requested.every((t) => t === "cards");
}

function buildCardsRedirectPath(searchParams: URLSearchParams): string {
  const q = (searchParams.get("q") ?? "").trim().slice(0, MAX_REDIRECT_QUERY_LENGTH);
  return q ? `/cards?q=${encodeURIComponent(q)}` : "/cards";
}

const TYPE_LABELS: Record<SearchType, string> = {
  cards: "Cards",
  collection: "Collection",
  wishlist: "Wishlist",
  grading: "Grading",
  notes: "Notes",
  activity: "Activity",
  signals: "Signals",
  opportunities: "Opportunities",
  reports: "Reports",
};

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 350;
const LIMIT_OPTIONS = [50, 100, 200] as const;

function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "not available";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function groupByType(results: SearchResult[]): Partial<Record<SearchType, SearchResult[]>> {
  const groups: Partial<Record<SearchType, SearchResult[]>> = {};
  for (const result of results) {
    if (!groups[result.type]) groups[result.type] = [];
    groups[result.type]!.push(result);
  }
  return groups;
}

export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SearchPageRedirectGate />
    </Suspense>
  );
}

/** Reads the query string once to decide redirect-vs-render - split out from
 * SearchPageInner so a redirect never mounts (and never fetches suggestions
 * for) the full command-center UI below it. */
function SearchPageRedirectGate() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = shouldRedirectToCards(searchParams);

  useEffect(() => {
    if (redirect) router.replace(buildCardsRedirectPath(searchParams));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [redirect, searchParams.toString()]);

  if (redirect) return null;
  return <SearchPageInner />;
}

function SearchPageInner() {
  const [input, setInput] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [activeType, setActiveType] = useState<SearchType | null>(null);

  const [results, setResults] = useState<SearchResult[]>([]);
  const [summary, setSummary] = useState<SearchSummary | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "ready">("idle");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Debounce the raw input into a submitted query - matches the 300ms
  // debounce pattern already used on the opportunities page's free-text
  // filters, so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      setSubmittedQuery(input.trim());
    }, DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [input]);

  const showSuggestions = submittedQuery.length < MIN_QUERY_LENGTH;
  const showResults = !showSuggestions;

  // Suggestions: shown before a real query is submitted (empty input, or an
  // input too short to search), filtered live by whatever's been typed.
  useEffect(() => {
    if (!showSuggestions) return;
    let cancelled = false;
    fetchSearchSuggestions({ q: input.trim() || undefined })
      .then((data) => {
        if (!cancelled) setSuggestions(data.suggestions);
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [input, showSuggestions]);

  // A new query or type filter re-pages to the start - an offset from the
  // old result set is otherwise almost certainly out of range for the new
  // one.
  useEffect(() => {
    setOffset(0);
  }, [submittedQuery, activeType, limit]);

  useEffect(() => {
    if (!showResults) return;
    setStatus("loading");
    fetchSearch({
      q: submittedQuery,
      types: activeType ? [activeType] : undefined,
      limit,
      offset,
    })
      .then((data) => {
        setResults(data.results);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [submittedQuery, activeType, showResults, limit, offset]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmittedQuery(input.trim());
  }

  const grouped = useMemo(() => groupByType(results), [results]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader title="Search Command Center" />

        <form onSubmit={handleSubmit} className="mb-4">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search cards, collection, wishlist, grading, notes, activity, signals, opportunities, reports…"
            className="w-full rounded-panel border border-border-default bg-bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-sky-600 focus:outline-none"
          />
        </form>

        <div className="mb-4 flex flex-wrap gap-1.5">
          <TypeChip
            label="All"
            active={activeType === null}
            onClick={() => setActiveType(null)}
          />
          {SEARCH_TYPES.map((t) => (
            <TypeChip
              key={t}
              label={TYPE_LABELS[t]}
              active={activeType === t}
              onClick={() => setActiveType(t)}
            />
          ))}
        </div>

        {showSuggestions && (
          <div className="space-y-4">
            <div className="panel p-6 text-center text-sm text-text-muted">
              Search for a card, note, wishlist target, grading submission, or signal.
            </div>
            {suggestions.length > 0 && (
              <div>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
                  Suggestions
                </h2>
                <div className="panel divide-y divide-border-muted">
                  {suggestions.map((s, i) => (
                    <Link
                      key={`${s.type}-${s.label}-${i}`}
                      href={s.url}
                      className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-bg-elevated"
                    >
                      <span className="truncate text-text-primary">{s.label}</span>
                      <SearchTypeBadge type={s.type} />
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {showResults && status === "loading" && <LoadingState>Searching…</LoadingState>}

        {showResults && status === "error" && (
          <ErrorState>Failed to search. Try again.</ErrorState>
        )}

        {showResults && status === "ready" && summary && (
          <>
            <div className="mb-4 text-xs text-text-muted">
              {summary.total_results} result{summary.total_results === 1 ? "" : "s"} for{" "}
              <span className="text-text-secondary">&ldquo;{submittedQuery}&rdquo;</span>
            </div>

            {results.length === 0 && <EmptyState>No results found</EmptyState>}

            <div className="space-y-6">
              {SEARCH_TYPES.filter((t) => grouped[t] && grouped[t]!.length > 0).map((t) => (
                <section key={t}>
                  <h2 className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-muted">
                    {TYPE_LABELS[t]}
                    <span className="text-text-faint">({grouped[t]!.length})</span>
                  </h2>
                  <div className="panel divide-y divide-border-muted">
                    {grouped[t]!.map((result) => (
                      <ResultRow key={`${result.type}-${result.id}`} result={result} />
                    ))}
                  </div>
                </section>
              ))}
            </div>

            <div className="mt-4">
              <PaginationControls
                offset={offset}
                limit={limit}
                total={summary.total_results}
                onOffsetChange={setOffset}
                limitOptions={LIMIT_OPTIONS}
                onLimitChange={setLimit}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function TypeChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
        active
          ? "bg-accent-gold/15 text-accent-gold ring-accent-gold/40"
          : "text-text-secondary ring-border-default hover:text-text-primary"
      }`}
    >
      {label}
    </button>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  const metadataEntries = Object.entries(result.metadata).filter(([, v]) => v !== undefined);

  return (
    <div className="flex items-start justify-between gap-3 px-3 py-2.5 hover:bg-bg-elevated">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <SearchTypeBadge type={result.type} />
          <span className="truncate text-sm font-medium text-text-primary">{result.title}</span>
          <span className="shrink-0 text-xs font-semibold text-text-muted">
            score {result.score}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-text-muted">{result.subtitle}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-faint">
          {result.card_code && (
            <span className="mono text-text-muted">{result.card_code}</span>
          )}
          {result.matched_fields.length > 0 && (
            <span>matched: {result.matched_fields.join(", ")}</span>
          )}
          {metadataEntries.map(([key, value]) => (
            <span key={key}>
              {key}: {formatMetadataValue(value)}
            </span>
          ))}
        </div>
      </div>
      <Link
        href={result.url}
        className="shrink-0 whitespace-nowrap text-xs font-medium text-sky-400 hover:text-sky-300"
      >
        Open
      </Link>
    </div>
  );
}
