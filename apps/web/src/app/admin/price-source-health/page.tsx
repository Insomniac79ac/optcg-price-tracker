"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import {
  AdminAuthRequiredError,
  type HealthCoverageBreakdownItem,
  type PriceGapItem,
  type PriceSourceHealthGapType,
  type PriceSourceHealthReport,
  type SourceHealthItem,
  fetchPriceSourceHealth,
  fetchPriceSourceHealthGaps,
} from "@/lib/api";
import { formatDateTime, formatJpy, formatNullable, formatNumber, formatPercent } from "@/lib/format";

const NOT_AVAILABLE = "not available";
const na = <T,>(value: T | null | undefined, formatter: (v: T) => string) =>
  formatNullable(value, formatter, NOT_AVAILABLE);

const GAP_TABS: { value: PriceSourceHealthGapType; label: string; emptyLabel: string }[] = [
  { value: "stale", label: "Stale prices", emptyLabel: "No stale prices found" },
  { value: "missing", label: "Missing prices", emptyLabel: "No missing prices found" },
  { value: "failed_refresh", label: "Failed refreshes", emptyLabel: "No failed refreshes found" },
  { value: "blocked", label: "Blocked", emptyLabel: "No blocked sources found" },
  { value: "low_coverage", label: "Low coverage", emptyLabel: "No low coverage gaps found" },
];

const HEALTH_STYLES: Record<string, string> = {
  healthy: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  degraded: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  stale: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  blocked: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  error: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  unknown: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  review: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
};

function HealthBadge({ status }: { status: string }) {
  const style = HEALTH_STYLES[status] ?? "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {status}
    </span>
  );
}

function SeverityPill({ severity }: { severity: string }) {
  const style = SEVERITY_STYLES[severity] ?? "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {severity}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function SourceHealthTable({ sources }: { sources: SourceHealthItem[] }) {
  if (sources.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
        No sources found.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[1100px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
            <th className="px-3 py-2 font-medium">Source</th>
            <th className="px-3 py-2 font-medium">Health</th>
            <th className="px-3 py-2 text-right font-medium">Active mappings</th>
            <th className="px-3 py-2 text-right font-medium">Recent</th>
            <th className="px-3 py-2 text-right font-medium">Stale</th>
            <th className="px-3 py-2 text-right font-medium">Missing</th>
            <th className="px-3 py-2 font-medium">Latest price</th>
            <th className="px-3 py-2 font-medium">Latest refresh</th>
            <th className="px-3 py-2 font-medium">Started</th>
            <th className="px-3 py-2 font-medium">Finished</th>
            <th className="px-3 py-2 text-right font-medium">Success rate</th>
            <th className="px-3 py-2 text-right font-medium">Avg duration</th>
            <th className="px-3 py-2 text-right font-medium">Blocked 7d</th>
            <th className="px-3 py-2 text-right font-medium">Errors 7d</th>
            <th className="px-3 py-2 font-medium">Warnings</th>
            <th className="px-3 py-2 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source_id} className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
              <td className="px-3 py-2 font-medium text-neutral-200">{s.source_name}</td>
              <td className="px-3 py-2">
                <HealthBadge status={s.health_status} />
              </td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.active_mapping_count)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.recent_price_count)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.stale_price_count)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.missing_price_count)}</td>
              <td className="px-3 py-2 text-xs text-neutral-500">{na(s.latest_price_observed_at, formatDateTime)}</td>
              <td className="px-3 py-2 text-neutral-400">{na(s.latest_refresh_status, (v) => v)}</td>
              <td className="px-3 py-2 text-xs text-neutral-500">{na(s.latest_refresh_started_at, formatDateTime)}</td>
              <td className="px-3 py-2 text-xs text-neutral-500">{na(s.latest_refresh_finished_at, formatDateTime)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatPercent(s.recent_refresh_success_rate_pct)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">
                {na(s.average_refresh_duration_seconds, (v) => `${v}s`)}
              </td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.blocked_count_7d)}</td>
              <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(s.error_count_7d)}</td>
              <td className="px-3 py-2 max-w-[12rem]">
                <div className="flex flex-col gap-1">
                  {s.warnings.length === 0 ? (
                    <span className="text-xs text-neutral-600">{NOT_AVAILABLE}</span>
                  ) : (
                    s.warnings.map((w, idx) => (
                      <span key={idx} className="text-xs text-amber-400">
                        {w}
                      </span>
                    ))
                  )}
                </div>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-2 text-xs">
                  <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:underline">
                    Mapping quality
                  </Link>
                  <Link href="/admin/refresh-runs" className="text-sky-400 hover:underline">
                    Refresh runs
                  </Link>
                  <Link href="/admin/logs" className="text-sky-400 hover:underline">
                    Logs
                  </Link>
                  <Link href="/admin/actions" className="text-sky-400 hover:underline">
                    Run refresh
                  </Link>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakdownTable({ title, items }: { title: string; items: HealthCoverageBreakdownItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm text-neutral-500">
        <div className="mb-2 text-sm font-medium text-neutral-300">{title}</div>
        No data.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900">
      <div className="border-b border-neutral-800 px-4 py-2 text-sm font-medium text-neutral-300">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-xs uppercase tracking-wide text-neutral-500">
              <th className="px-3 py-2 font-medium">Label</th>
              <th className="px-3 py-2 text-right font-medium">Mapped</th>
              <th className="px-3 py-2 text-right font-medium">Recent</th>
              <th className="px-3 py-2 text-right font-medium">Stale</th>
              <th className="px-3 py-2 text-right font-medium">Missing</th>
              <th className="px-3 py-2 text-right font-medium">Coverage %</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key} className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
                <td className="px-3 py-2 font-medium text-neutral-200">{item.label}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.mapped_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.recent_price_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.stale_price_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.missing_price_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatPercent(item.coverage_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PriceSourceHealthPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [report, setReport] = useState<PriceSourceHealthReport | null>(null);

  const [source, setSource] = useState("");
  const [setCode, setSetCode] = useState("");
  const [rarity, setRarity] = useState("");
  const [variant, setVariant] = useState("");
  const [language, setLanguage] = useState("");
  const [includeInactiveMappings, setIncludeInactiveMappings] = useState(false);

  const [activeTab, setActiveTab] = useState<PriceSourceHealthGapType>("stale");
  const [gapItems, setGapItems] = useState<PriceGapItem[]>([]);
  const [gapTotal, setGapTotal] = useState(0);
  const [gapStatus, setGapStatus] = useState<"loading" | "error" | "ready">("loading");
  const [gapLimit, setGapLimit] = useState(50);
  const [gapOffset, setGapOffset] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchPriceSourceHealth({
      source: source || undefined,
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      variant: variant || undefined,
      language: language || undefined,
      include_inactive_mappings: includeInactiveMappings,
    })
      .then((data) => {
        if (cancelled) return;
        setReport(data);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [source, setCode, rarity, variant, language, includeInactiveMappings]);

  useEffect(() => {
    setGapOffset(0);
  }, [activeTab, source, setCode, rarity]);

  useEffect(() => {
    let cancelled = false;
    setGapStatus("loading");
    fetchPriceSourceHealthGaps({
      gap_type: activeTab,
      source: source || undefined,
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      limit: gapLimit,
      offset: gapOffset,
    })
      .then((data) => {
        if (cancelled) return;
        setGapItems(data.items);
        setGapTotal(data.pagination.total);
        setGapStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setGapStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, source, setCode, rarity, gapLimit, gapOffset]);

  const summary = report?.summary;
  const activeTabMeta = GAP_TABS.find((t) => t.value === activeTab)!;

  const summaryCards: { label: string; value: string }[] = summary
    ? [
        { label: "Sources", value: formatNumber(summary.sources_count) },
        { label: "Active sources", value: formatNumber(summary.active_sources_count) },
        { label: "Active mappings", value: formatNumber(summary.total_active_mappings) },
        { label: "With recent price", value: formatNumber(summary.mappings_with_recent_price) },
        { label: "Without recent price", value: formatNumber(summary.mappings_without_recent_price) },
        { label: "Stale prices", value: formatNumber(summary.stale_price_count) },
        { label: "Missing prices", value: formatNumber(summary.missing_price_count) },
        { label: "Last successful refresh", value: na(summary.last_successful_refresh_at, formatDateTime) },
        { label: "Last failed refresh", value: na(summary.last_failed_refresh_at, formatDateTime) },
        { label: "Recent success rate", value: formatPercent(summary.recent_refresh_success_rate_pct) },
        { label: "Blocked sources", value: formatNumber(summary.blocked_source_count) },
        { label: "Error sources", value: formatNumber(summary.error_source_count) },
      ]
    : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex flex-wrap items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-100">Price Source Health</h1>
          <Link href="/admin/catalog-coverage" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Catalog coverage →
          </Link>
          <Link href="/admin/source-mapping-quality" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Mapping quality →
          </Link>
          <Link href="/admin/refresh-runs" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Refresh runs →
          </Link>
          <Link href="/admin/card-audit" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Card audit →
          </Link>
          <Link href="/admin/system-check" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            System check →
          </Link>
          <Link href="/admin/catalog-ops" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Catalog operations →
          </Link>
          <span className="ml-auto">
            <AdminLogoutButton />
          </span>
        </div>
        <p className="mb-2 text-sm text-neutral-500">
          Track source freshness, refresh reliability, stale prices, and missing price coverage.
        </p>
        <p className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs text-neutral-500">
          SNKRDUNK automated discovery can be blocked. Do not bypass site protections; use manual
          imports when needed.
        </p>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            {report && report.warnings.length > 0 && (
              <div className="mb-4 rounded-lg border border-amber-900/50 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
                <div className="mb-1 font-medium">Warnings</div>
                <ul className="list-inside list-disc space-y-0.5">
                  {report.warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100">
                <option value="">Any source</option>
                <option value="yuyutei">yuyutei</option>
                <option value="snkrdunk">snkrdunk</option>
              </select>
              <input
                value={setCode}
                onChange={(e) => setSetCode(e.target.value)}
                placeholder="Set code (e.g. OP01)…"
                className="w-40 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                placeholder="Rarity…"
                className="w-28 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Variant…"
                className="w-32 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="Language…"
                className="w-28 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
              />
              <label className="flex items-center gap-1.5 text-sm text-neutral-400">
                <input
                  type="checkbox"
                  checked={includeInactiveMappings}
                  onChange={(e) => setIncludeInactiveMappings(e.target.checked)}
                />
                Include inactive mappings
              </label>
            </div>

            {status === "loading" && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                Loading price source health…
              </div>
            )}
            {status === "error" && (
              <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load price source health from the API. Is the backend running?
              </div>
            )}

            {status === "ready" && report && (
              <>
                <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {summaryCards.map((c) => (
                    <StatCard key={c.label} label={c.label} value={c.value} />
                  ))}
                </div>

                <div className="mb-6">
                  <SourceHealthTable sources={report.sources} />
                </div>

                <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <BreakdownTable title="Coverage by set" items={report.coverage_by_set} />
                  <BreakdownTable title="Coverage by rarity" items={report.coverage_by_rarity} />
                </div>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  {GAP_TABS.map((tab) => (
                    <button
                      key={tab.value}
                      onClick={() => setActiveTab(tab.value)}
                      className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                        activeTab === tab.value
                          ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                          : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {gapStatus === "loading" && (
                  <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                    Loading {activeTabMeta.label.toLowerCase()}…
                  </div>
                )}
                {gapStatus === "error" && (
                  <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                    Failed to load {activeTabMeta.label.toLowerCase()}.
                  </div>
                )}
                {gapStatus === "ready" && gapItems.length === 0 && (
                  <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                    {activeTabMeta.emptyLabel}
                  </div>
                )}
                {gapStatus === "ready" && gapItems.length > 0 && (
                  <div className="overflow-x-auto rounded-lg border border-neutral-800">
                    <table className="w-full min-w-[1000px] border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                          <th className="px-3 py-2 font-medium">Severity</th>
                          <th className="px-3 py-2 font-medium">Source</th>
                          <th className="px-3 py-2 font-medium">Card code</th>
                          <th className="px-3 py-2 font-medium">Name</th>
                          <th className="px-3 py-2 font-medium">Set</th>
                          <th className="px-3 py-2 font-medium">Rarity</th>
                          <th className="px-3 py-2 font-medium">Variant</th>
                          <th className="px-3 py-2 font-medium">Latest price observed</th>
                          <th className="px-3 py-2 font-medium">Price type</th>
                          <th className="px-3 py-2 font-medium">Latest price</th>
                          <th className="px-3 py-2 font-medium">Issue type</th>
                          <th className="px-3 py-2 font-medium">Suggested action</th>
                          <th className="px-3 py-2 font-medium">Links</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gapItems.map((item) => (
                          <tr
                            key={`${item.mapping_id}-${item.issue_type}`}
                            className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                          >
                            <td className="px-3 py-2">
                              <SeverityPill severity={item.severity} />
                            </td>
                            <td className="px-3 py-2 text-neutral-400">{item.source_name}</td>
                            <td className="px-3 py-2 font-mono text-xs text-neutral-300">
                              {na(item.card_code, (v) => v)}
                            </td>
                            <td className="px-3 py-2 text-neutral-300">{na(item.name_en, (v) => v)}</td>
                            <td className="px-3 py-2 text-neutral-400">{na(item.set_code, (v) => v)}</td>
                            <td className="px-3 py-2 text-neutral-400">{na(item.rarity, (v) => v)}</td>
                            <td className="px-3 py-2 text-neutral-400">{na(item.variant, (v) => v)}</td>
                            <td className="px-3 py-2 text-xs text-neutral-500">
                              {na(item.latest_price_observed_at, formatDateTime)}
                            </td>
                            <td className="px-3 py-2 text-neutral-400">{na(item.latest_price_type, (v) => v)}</td>
                            <td className="px-3 py-2 text-neutral-400">{na(item.latest_price_jpy, formatJpy)}</td>
                            <td className="px-3 py-2 font-mono text-xs text-neutral-400">{item.issue_type}</td>
                            <td className="px-3 py-2 text-xs text-neutral-500">{item.suggested_action}</td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-2 text-xs">
                                <Link href={`/cards/${item.card_id}`} className="text-sky-400 hover:underline">
                                  Card
                                </Link>
                                <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:underline">
                                  Mapping quality
                                </Link>
                                <Link href="/admin/refresh-runs" className="text-sky-400 hover:underline">
                                  Refresh runs
                                </Link>
                                <Link href="/admin/logs" className="text-sky-400 hover:underline">
                                  Logs
                                </Link>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {gapStatus === "ready" && (
                  <div className="mt-3">
                    <PaginationControls
                      offset={gapOffset}
                      limit={gapLimit}
                      total={gapTotal}
                      onOffsetChange={setGapOffset}
                      limitOptions={[25, 50, 100, 200]}
                      onLimitChange={setGapLimit}
                    />
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
