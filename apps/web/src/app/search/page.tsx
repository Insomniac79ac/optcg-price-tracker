"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { SearchTypeBadge } from "@/components/SearchTypeBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  SEARCH_TYPES,
  type SearchResult,
  type SearchSuggestion,
  type SearchSummary,
  type SearchType,
  fetchSearch,
  fetchSearchSuggestions,
} from "@/lib/api";

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
  const [input, setInput] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [activeType, setActiveType] = useState<SearchType | null>(null);

  const [results, setResults] = useState<SearchResult[]>([]);
  const [summary, setSummary] = useState<SearchSummary | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "ready">("idle");

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

  useEffect(() => {
    if (!showResults) return;
    setStatus("loading");
    fetchSearch({
      q: submittedQuery,
      types: activeType ? [activeType] : undefined,
      limit: 200,
    })
      .then((data) => {
        setResults(data.results);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [submittedQuery, activeType, showResults]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmittedQuery(input.trim());
  }

  const grouped = useMemo(() => groupByType(results), [results]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <h1 className="mb-4 text-lg font-semibold text-neutral-100">Search Command Center</h1>

        <form onSubmit={handleSubmit} className="mb-4">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search cards, collection, wishlist, grading, notes, activity, signals, opportunities, reports…"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-sky-600 focus:outline-none"
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
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-6 text-center text-sm text-neutral-500">
              Search for a card, note, wishlist target, grading submission, or signal.
            </div>
            {suggestions.length > 0 && (
              <div>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                  Suggestions
                </h2>
                <div className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
                  {suggestions.map((s, i) => (
                    <Link
                      key={`${s.type}-${s.label}-${i}`}
                      href={s.url}
                      className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-neutral-900/60"
                    >
                      <span className="truncate text-neutral-200">{s.label}</span>
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
            <div className="mb-4 text-xs text-neutral-500">
              {summary.total_results} result{summary.total_results === 1 ? "" : "s"} for{" "}
              <span className="text-neutral-300">&ldquo;{submittedQuery}&rdquo;</span>
            </div>

            {results.length === 0 && <EmptyState>No results found</EmptyState>}

            <div className="space-y-6">
              {SEARCH_TYPES.filter((t) => grouped[t] && grouped[t]!.length > 0).map((t) => (
                <section key={t}>
                  <h2 className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                    {TYPE_LABELS[t]}
                    <span className="text-neutral-700">({grouped[t]!.length})</span>
                  </h2>
                  <div className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
                    {grouped[t]!.map((result) => (
                      <ResultRow key={`${result.type}-${result.id}`} result={result} />
                    ))}
                  </div>
                </section>
              ))}
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
      className={`rounded px-2.5 py-1 text-xs font-medium ${
        active
          ? "bg-neutral-100 text-neutral-900"
          : "border border-neutral-700 text-neutral-400 hover:text-neutral-100"
      }`}
    >
      {label}
    </button>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  const metadataEntries = Object.entries(result.metadata).filter(([, v]) => v !== undefined);

  return (
    <div className="flex items-start justify-between gap-3 px-3 py-2.5 hover:bg-neutral-900/60">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <SearchTypeBadge type={result.type} />
          <span className="truncate text-sm font-medium text-neutral-100">{result.title}</span>
          <span className="shrink-0 text-xs font-semibold text-neutral-500">
            score {result.score}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-neutral-500">{result.subtitle}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neutral-600">
          {result.card_code && (
            <span className="font-mono text-neutral-500">{result.card_code}</span>
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
