"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { PriceCell } from "@/components/ui/PriceCell";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { SourceHealthBadge, type SourceHealth } from "@/components/ui/SourceHealthBadge";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
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
import { formatDateTime, formatNullable, formatNumber, formatPercent } from "@/lib/format";

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

// source-mapping-quality/import-validation-style "review/warning/critical"
// severity vocab - RiskBadge already aliases this onto the canonical
// low/medium/high/critical scale.
function severityToRisk(severity: string): "low" | "medium" | "high" | "critical" {
  if (severity === "review") return "medium";
  if (severity === "warning") return "high";
  if (severity === "critical") return "critical";
  return "medium";
}

function SourceHealthTable({ sources }: { sources: SourceHealthItem[] }) {
  if (sources.length === 0) {
    return (
      <div className="rounded-panel border border-border-default bg-bg-surface p-8 text-center text-sm text-text-muted">
        No sources found.
      </div>
    );
  }

  return (
    <DataTableShell>
      <table className="data-table min-w-[1100px]">
        <thead>
          <tr>
            <th>Source</th>
            <th>Health</th>
            <th className="text-right">Active mappings</th>
            <th className="text-right">Recent</th>
            <th className="text-right">Stale</th>
            <th className="text-right">Missing</th>
            <th>Latest price</th>
            <th>Latest refresh</th>
            <th>Started</th>
            <th>Finished</th>
            <th className="text-right">Success rate</th>
            <th className="text-right">Avg duration</th>
            <th className="text-right">Blocked 7d</th>
            <th className="text-right">Errors 7d</th>
            <th>Warnings</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source_id}>
              <td className="font-medium text-text-primary">{s.source_name}</td>
              <td>
                <SourceHealthBadge health={s.health_status as SourceHealth} />
              </td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.active_mapping_count)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.recent_price_count)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.stale_price_count)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.missing_price_count)}</td>
              <td className="mono text-[11px] text-text-muted">{na(s.latest_price_observed_at, formatDateTime)}</td>
              <td className="text-text-secondary">{na(s.latest_refresh_status, (v) => v)}</td>
              <td className="mono text-[11px] text-text-muted">{na(s.latest_refresh_started_at, formatDateTime)}</td>
              <td className="mono text-[11px] text-text-muted">{na(s.latest_refresh_finished_at, formatDateTime)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatPercent(s.recent_refresh_success_rate_pct)}</td>
              <td className="mono tabular text-right text-text-secondary">
                {na(s.average_refresh_duration_seconds, (v) => `${v}s`)}
              </td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.blocked_count_7d)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(s.error_count_7d)}</td>
              <td className="max-w-[12rem]">
                <div className="flex flex-col gap-1">
                  {s.warnings.length === 0 ? (
                    <span className="text-[11px] text-text-faint">{NOT_AVAILABLE}</span>
                  ) : (
                    s.warnings.map((w, idx) => (
                      <span key={idx} className="text-[11px] text-signal-warning">
                        {w}
                      </span>
                    ))
                  )}
                </div>
              </td>
              <td>
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
    </DataTableShell>
  );
}

function BreakdownTable({ title, items }: { title: string; items: HealthCoverageBreakdownItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-panel border border-border-default bg-bg-surface p-4 text-sm text-text-muted">
        <div className="mb-2 text-sm font-medium text-text-secondary">{title}</div>
        No data.
      </div>
    );
  }

  return (
    <div className="panel overflow-hidden">
      <div className="border-b border-border-default px-4 py-2 text-sm font-medium text-text-secondary">{title}</div>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[600px]">
          <thead>
            <tr>
              <th>Label</th>
              <th className="text-right">Mapped</th>
              <th className="text-right">Recent</th>
              <th className="text-right">Stale</th>
              <th className="text-right">Missing</th>
              <th className="text-right">Coverage %</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key}>
                <td className="font-medium text-text-primary">{item.label}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(item.mapped_cards)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(item.recent_price_cards)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(item.stale_price_cards)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(item.missing_price_cards)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatPercent(item.coverage_pct)}</td>
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
        <PageHeader
          title="Price Source Health"
          actions={<AdminLogoutButton />}
          description={
            <>
              <span className="mb-2 block">
                Track source freshness, refresh reliability, stale prices, and missing price
                coverage.
              </span>
              <span className="mb-2 flex flex-wrap gap-3 text-xs">
                <Link href="/admin/catalog-coverage" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  Catalog coverage →
                </Link>
                <Link href="/admin/source-mapping-quality" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  Mapping quality →
                </Link>
                <Link href="/admin/refresh-runs" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  Refresh runs →
                </Link>
                <Link href="/admin/card-audit" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  Card audit →
                </Link>
                <Link href="/admin/system-check" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  System check →
                </Link>
                <Link href="/admin/catalog-ops" className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
                  Catalog operations →
                </Link>
              </span>
            </>
          }
        />
        <p className="mb-4 rounded-panel border border-border-default bg-bg-surface px-3 py-2 text-xs text-text-muted">
          SNKRDUNK automated discovery can be blocked. Do not bypass site protections; use manual
          imports when needed.
        </p>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            {report && report.warnings.length > 0 && (
              <div className="mb-4 rounded-panel border border-signal-warning/40 bg-signal-warning/10 px-4 py-3 text-sm text-signal-warning">
                <div className="mb-1 font-medium">Warnings</div>
                <ul className="list-inside list-disc space-y-0.5">
                  {report.warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary">
                <option value="">Any source</option>
                <option value="yuyutei">yuyutei</option>
                <option value="snkrdunk">snkrdunk</option>
              </select>
              <input
                value={setCode}
                onChange={(e) => setSetCode(e.target.value)}
                placeholder="Set code (e.g. OP01)…"
                className="w-40 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
              />
              <input
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                placeholder="Rarity…"
                className="w-28 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
              />
              <input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Variant…"
                className="w-32 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
              />
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="Language…"
                className="w-28 rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
              />
              <label className="flex items-center gap-1.5 text-sm text-text-secondary">
                <input
                  type="checkbox"
                  checked={includeInactiveMappings}
                  onChange={(e) => setIncludeInactiveMappings(e.target.checked)}
                />
                Include inactive mappings
              </label>
            </div>

            <SavedViewBar
              routePath="/admin/price-source-health"
              viewType="price_source_health"
              scope="admin"
              currentFilters={{
                source,
                setCode,
                rarity,
                variant,
                language,
                includeInactiveMappings,
                activeTab,
              }}
              onApply={(filters) => {
                if (typeof filters.source === "string") setSource(filters.source);
                if (typeof filters.setCode === "string") setSetCode(filters.setCode);
                if (typeof filters.rarity === "string") setRarity(filters.rarity);
                if (typeof filters.variant === "string") setVariant(filters.variant);
                if (typeof filters.language === "string") setLanguage(filters.language);
                if (typeof filters.includeInactiveMappings === "boolean") {
                  setIncludeInactiveMappings(filters.includeInactiveMappings);
                }
                if (typeof filters.activeTab === "string") {
                  setActiveTab(filters.activeTab as PriceSourceHealthGapType);
                }
                setGapOffset(0);
              }}
            />

            {status === "loading" && (
              <div className="rounded-panel border border-border-default bg-bg-surface p-8 text-center text-sm text-text-muted">
                Loading price source health…
              </div>
            )}
            {status === "error" && (
              <div className="rounded-panel border border-signal-red/40 bg-signal-red/10 p-8 text-center text-sm text-signal-red">
                Failed to load price source health from the API. Is the backend running?
              </div>
            )}

            {status === "ready" && report && (
              <>
                <div className="mb-6">
                  <StatGrid>
                    {summaryCards.map((c) => (
                      <StatCard key={c.label} label={c.label} value={c.value} />
                    ))}
                  </StatGrid>
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
                      className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                        activeTab === tab.value
                          ? "bg-accent-gold text-black/80 ring-accent-gold"
                          : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {gapStatus === "loading" && (
                  <div className="rounded-panel border border-border-default bg-bg-surface p-8 text-center text-sm text-text-muted">
                    Loading {activeTabMeta.label.toLowerCase()}…
                  </div>
                )}
                {gapStatus === "error" && (
                  <div className="rounded-panel border border-signal-red/40 bg-signal-red/10 p-8 text-center text-sm text-signal-red">
                    Failed to load {activeTabMeta.label.toLowerCase()}.
                  </div>
                )}
                {gapStatus === "ready" && gapItems.length === 0 && (
                  <div className="rounded-panel border border-border-default bg-bg-surface p-8 text-center text-sm text-text-muted">
                    {activeTabMeta.emptyLabel}
                  </div>
                )}
                {gapStatus === "ready" && gapItems.length > 0 && (
                  <DataTableShell>
                    <table className="data-table min-w-[1000px]">
                      <thead>
                        <tr>
                          <th>Severity</th>
                          <th>Source</th>
                          <th>Card code</th>
                          <th>Name</th>
                          <th>Set</th>
                          <th>Rarity</th>
                          <th>Variant</th>
                          <th>Latest price observed</th>
                          <th>Price type</th>
                          <th>Latest price</th>
                          <th>Issue type</th>
                          <th>Suggested action</th>
                          <th>Links</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gapItems.map((item) => (
                          <tr key={`${item.mapping_id}-${item.issue_type}`}>
                            <td>
                              <RiskBadge level={severityToRisk(item.severity)} />
                            </td>
                            <td className="text-text-secondary">{item.source_name}</td>
                            <td className="mono text-xs text-text-secondary">
                              {na(item.card_code, (v) => v)}
                            </td>
                            <td className="text-text-secondary">{na(item.name_en, (v) => v)}</td>
                            <td className="text-text-secondary">{na(item.set_code, (v) => v)}</td>
                            <td className="text-text-secondary">{na(item.rarity, (v) => v)}</td>
                            <td className="text-text-secondary">{na(item.variant, (v) => v)}</td>
                            <td className="mono text-[11px] text-text-muted">
                              {na(item.latest_price_observed_at, formatDateTime)}
                            </td>
                            <td className="text-text-secondary">{na(item.latest_price_type, (v) => v)}</td>
                            <td>
                              <PriceCell
                                valueJpy={item.latest_price_jpy}
                                observedAt={item.latest_price_observed_at}
                                size="sm"
                              />
                            </td>
                            <td className="mono text-xs text-text-secondary">{item.issue_type}</td>
                            <td className="text-xs text-text-muted">{item.suggested_action}</td>
                            <td>
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
                  </DataTableShell>
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
