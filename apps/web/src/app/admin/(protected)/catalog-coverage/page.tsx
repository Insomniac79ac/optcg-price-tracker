"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard as SharedStatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type CatalogCoverageGapItem,
  type CatalogCoverageGapType,
  type CatalogCoverageReport,
  type PhysicalPrintCoverageBreakdown,
  fetchCatalogCoverage,
  fetchCatalogCoverageGaps,
} from "@/lib/api";
import { formatNullable, formatNumber, formatPercent } from "@/lib/format";

const NOT_AVAILABLE = "not available";

const GAP_TABS: { value: CatalogCoverageGapType; label: string; emptyLabel: string }[] = [
  { value: "mapping", label: "Exact mapping gaps", emptyLabel: "No physical prints without exact source mappings" },
  { value: "price", label: "Fresh price gaps", emptyLabel: "No mapped physical prints without fresh observations" },
  { value: "metadata", label: "Compatibility metadata gaps", emptyLabel: "No legacy compatibility metadata gaps found" },
  { value: "duplicate", label: "Compatibility duplicate risks", emptyLabel: "No legacy compatibility duplicate risks found" },
  { value: "mapping_quality", label: "Compatibility mapping risks", emptyLabel: "No legacy compatibility mapping risks found" },
];

const SEVERITY_OPTIONS = ["", "critical", "warning", "review"];

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  review: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
};

function SeverityPill({ severity }: { severity: string }) {
  const style = SEVERITY_STYLES[severity] ?? "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {severity}
    </span>
  );
}

const BREAKDOWN_LIMIT_OPTIONS = [10, 25, 50] as const;

function BreakdownTable({ title, items }: { title: string; items: PhysicalPrintCoverageBreakdown[] }) {
  const [visible, setVisible] = useState(25);

  if (items.length === 0) {
    return (
      <div className="rounded-panel border border-border-default bg-bg-surface p-4 text-sm text-text-muted">
        <div className="mb-2 text-sm font-medium text-text-secondary">{title}</div>
        No data.
      </div>
    );
  }

  return (
    <div className="rounded-panel border border-border-default bg-bg-surface">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-2">
        <span className="text-sm font-medium text-text-secondary">{title}</span>
        {items.length > BREAKDOWN_LIMIT_OPTIONS[0] && (
          <select
            value={visible}
            onChange={(e) => setVisible(Number(e.target.value))}
            className="rounded border border-border-default bg-bg-page px-1.5 py-0.5 text-xs text-text-secondary"
          >
            {BREAKDOWN_LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                Show {n}
              </option>
            ))}
            <option value={items.length}>Show all</option>
          </select>
        )}
      </div>
      <TableScrollContainer>
        <table className="w-full min-w-[700px] border-collapse text-sm">
          <thead className="sticky-thead">
            <tr className="border-b border-border-default text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="px-3 py-2 font-medium">Label</th>
              <th className="px-3 py-2 text-right font-medium">Eligible prints</th>
              <th className="px-3 py-2 text-right font-medium">Mapped prints</th>
              <th className="px-3 py-2 text-right font-medium">Fresh-price prints</th>
              <th className="px-3 py-2 text-right font-medium">Source mapping coverage</th>
              <th className="px-3 py-2 text-right font-medium">Fresh price coverage</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, visible).map((item) => (
              <tr key={item.key} className="border-b border-border-muted last:border-0 hover:bg-bg-elevated/60">
                <td className="px-3 py-2 font-medium text-text-primary">{item.label}</td>
                <td className="px-3 py-2 text-right text-text-secondary">{formatNumber(item.eligible_print_count)}</td>
                <td className="px-3 py-2 text-right text-text-secondary">{formatNumber(item.mapped_print_count)}</td>
                <td className="px-3 py-2 text-right text-text-secondary">{formatNumber(item.fresh_price_print_count)}</td>
                <td className="px-3 py-2 text-right text-text-secondary">{formatPercent(item.mapping_coverage_pct)}</td>
                <td className="px-3 py-2 text-right text-text-secondary">{formatPercent(item.fresh_price_coverage_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScrollContainer>
    </div>
  );
}

export default function CatalogCoveragePage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [report, setReport] = useState<CatalogCoverageReport | null>(null);

  const [setCode, setSetCode] = useState("");
  const [rarity, setRarity] = useState("");
  const [variant, setVariant] = useState("");
  const [language, setLanguage] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);

  const [activeTab, setActiveTab] = useState<CatalogCoverageGapType>("mapping");
  const [severity, setSeverity] = useState("");
  const [gapItems, setGapItems] = useState<CatalogCoverageGapItem[]>([]);
  const [gapTotal, setGapTotal] = useState(0);
  const [gapStatus, setGapStatus] = useState<"loading" | "error" | "ready">("loading");
  const [gapLimit, setGapLimit] = useState(50);
  const [gapOffset, setGapOffset] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Loading state follows a filter-driven external request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");
    fetchCatalogCoverage({
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      variant: variant || undefined,
      language: language || undefined,
      include_inactive: includeInactive,
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
  }, [setCode, rarity, variant, language, includeInactive]);

  useEffect(() => {
    // Reset pagination when the query identity changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGapOffset(0);
  }, [activeTab, severity, setCode, rarity, variant, language]);

  useEffect(() => {
    let cancelled = false;
    // Loading state follows a filter-driven external request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGapStatus("loading");
    fetchCatalogCoverageGaps({
      gap_type: activeTab,
      set_code: setCode || undefined,
      rarity: rarity || undefined,
      variant: variant || undefined,
      language: language || undefined,
      severity: severity || undefined,
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
  }, [activeTab, severity, setCode, rarity, variant, language, gapLimit, gapOffset]);

  const summary = report?.summary;
  const activeTabMeta = GAP_TABS.find((t) => t.value === activeTab)!;

  const summaryCards: { label: string; value: string }[] = summary
    ? [
        { label: "Eligible physical prints", value: formatNumber(summary.total_eligible_physical_prints) },
        { label: "Mapped physical prints", value: formatNumber(summary.prints_with_any_exact_mapping) },
        { label: "Fresh-price physical prints", value: formatNumber(summary.prints_with_any_fresh_source_observation) },
        { label: "No exact source mapping", value: formatNumber(summary.physical_prints_without_exact_mapping) },
        { label: "Mapped without fresh observation", value: formatNumber(summary.physical_prints_with_exact_mapping_but_no_fresh_observation) },
        { label: "Source mapping coverage", value: formatPercent(summary.exact_mapping_coverage_pct) },
        { label: "Fresh price coverage", value: formatPercent(summary.fresh_price_coverage_pct) },
        { label: "Exact source mappings", value: formatNumber(summary.exact_source_mapping_count) },
      ]
    : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Physical Print Coverage"
          description="Exact source mapping and fresh observation coverage for eligible physical prints."
        />
        <div className="mb-4 flex flex-wrap gap-3">
          <Link href="/admin/cards" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Card catalog →
          </Link>
          <Link href="/admin/card-audit" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Card audit →
          </Link>
          <Link href="/admin/source-mapping-quality" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Mapping quality →
          </Link>
          <Link href="/admin/card-duplicates" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Card duplicates →
          </Link>
          <Link href="/admin/price-source-health" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Price source health →
          </Link>
          <Link href="/admin/system-check" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            System check →
          </Link>
          <Link href="/admin/catalog-ops" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Catalog operations →
          </Link>
        </div>

        {unauthorized && <AdminSessionExpired />}

        {!unauthorized && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <input
                value={setCode}
                onChange={(e) => setSetCode(e.target.value)}
                placeholder="Set code (e.g. OP01)…"
                className={`w-40 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                placeholder="Rarity…"
                className={`w-28 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Variant…"
                className={`w-32 ${FILTER_INPUT_CLASS}`}
              />
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                placeholder="Language…"
                className={`w-28 ${FILTER_INPUT_CLASS}`}
              />
              <label className="flex items-center gap-1.5 text-sm text-text-secondary">
                <input
                  type="checkbox"
                  checked={includeInactive}
                  onChange={(e) => setIncludeInactive(e.target.checked)}
                />
                Include inactive
              </label>
            </div>

            <SavedViewBar
              routePath="/admin/catalog-coverage"
              viewType="catalog_coverage"
              scope="admin"
              currentFilters={{
                setCode,
                rarity,
                variant,
                language,
                includeInactive,
                activeTab,
                severity,
              }}
              onApply={(filters) => {
                if (typeof filters.setCode === "string") setSetCode(filters.setCode);
                if (typeof filters.rarity === "string") setRarity(filters.rarity);
                if (typeof filters.variant === "string") setVariant(filters.variant);
                if (typeof filters.language === "string") setLanguage(filters.language);
                if (typeof filters.includeInactive === "boolean") {
                  setIncludeInactive(filters.includeInactive);
                }
                if (typeof filters.activeTab === "string") {
                  setActiveTab(filters.activeTab as CatalogCoverageGapType);
                }
                if (typeof filters.severity === "string") setSeverity(filters.severity);
                setGapOffset(0);
              }}
            />

            {status === "loading" && <LoadingState>Loading physical print coverage…</LoadingState>}
            {status === "error" && (
              <ErrorState>Failed to load physical print coverage from the API. Is the backend running?</ErrorState>
            )}

            {status === "ready" && report && (
              <>
                <div className="mb-6">
                  <StatGrid>
                    {summaryCards.map((c) => (
                      <SharedStatCard key={c.label} label={c.label} value={c.value} />
                    ))}
                  </StatGrid>
                </div>

                <div className="mb-6 rounded-panel border border-border-default bg-bg-surface">
                  <div className="border-b border-border-default px-4 py-3">
                    <h2 className="font-medium text-text-primary">Per-source physical print coverage</h2>
                  </div>
                  <TableScrollContainer>
                    <table className="w-full min-w-[720px] border-collapse text-sm">
                      <thead className="sticky-thead"><tr className="text-left text-xs uppercase tracking-wide text-text-muted">
                        <th className="px-3 py-2 font-medium">Source</th><th className="px-3 py-2 text-right font-medium">Eligible prints</th><th className="px-3 py-2 text-right font-medium">Mapped prints</th><th className="px-3 py-2 text-right font-medium">Fresh-price prints</th><th className="px-3 py-2 text-right font-medium">Source mapping coverage</th><th className="px-3 py-2 text-right font-medium">Fresh price coverage</th>
                      </tr></thead>
                      <tbody>{report.sources.map((source) => <tr key={source.source_id} className="border-t border-border-muted">
                        <td className="px-3 py-2 font-medium text-text-primary">{source.source_name}</td><td className="px-3 py-2 text-right text-text-secondary">{formatNumber(source.eligible_print_count)}</td><td className="px-3 py-2 text-right text-text-secondary">{formatNumber(source.mapped_print_count)}</td><td className="px-3 py-2 text-right text-text-secondary">{formatNumber(source.fresh_price_print_count)}</td><td className="px-3 py-2 text-right text-text-secondary">{formatPercent(source.mapping_coverage_pct)}</td><td className="px-3 py-2 text-right text-text-secondary">{formatPercent(source.fresh_price_coverage_pct)}</td>
                      </tr>)}</tbody>
                    </table>
                  </TableScrollContainer>
                </div>

                <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <BreakdownTable title="Coverage by release product" items={report.coverage_by_release_product} />
                  <BreakdownTable title="Coverage by rarity" items={report.coverage_by_rarity} />
                  <BreakdownTable title="Coverage by language" items={report.coverage_by_language} />
                </div>

                <details className="mb-6 rounded-panel border border-border-default bg-bg-surface p-4">
                  <summary className="cursor-pointer font-medium text-text-secondary">Legacy compatibility catalogue metrics</summary>
                  <p className="mt-2 text-sm text-text-muted">Card-keyed catalogue, collection, and wishlist compatibility only. These totals are not physical-print pricing coverage.</p>
                  <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <SharedStatCard label="Legacy Cards" value={formatNumber(report.legacy_compatibility.summary.total_cards)} />
                    <SharedStatCard label="Legacy mapping coverage" value={formatPercent(report.legacy_compatibility.summary.mapping_coverage_pct)} />
                    <SharedStatCard label="Legacy recent-price coverage" value={formatPercent(report.legacy_compatibility.summary.recent_price_coverage_pct)} />
                    <SharedStatCard label="Legacy metadata completion" value={formatPercent(report.legacy_compatibility.summary.metadata_completion_pct)} />
                  </div>
                </details>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  {GAP_TABS.map((tab) => (
                    <button
                      key={tab.value}
                      type="button"
                      onClick={() => setActiveTab(tab.value)}
                      className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                        activeTab === tab.value
                          ? "bg-accent-gold text-black/80 ring-accent-gold"
                          : "bg-bg-surface text-text-muted ring-border-default hover:text-text-primary"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                    className={`ml-auto ${FILTER_INPUT_CLASS}`}
                  >
                    {SEVERITY_OPTIONS.map((v) => (
                      <option key={v} value={v}>
                        {v || "Any severity"}
                      </option>
                    ))}
                  </select>
                </div>

                {gapStatus === "loading" && (
                  <LoadingState>Loading {activeTabMeta.label.toLowerCase()}…</LoadingState>
                )}
                {gapStatus === "error" && (
                  <ErrorState>Failed to load {activeTabMeta.label.toLowerCase()}.</ErrorState>
                )}
                {gapStatus === "ready" && gapItems.length === 0 && (
                  <EmptyState>{activeTabMeta.emptyLabel}</EmptyState>
                )}
                {gapStatus === "ready" && gapItems.length > 0 && (
                  <TableScrollContainer>
                    <table className="w-full min-w-[900px] border-collapse text-sm">
                      <thead className="sticky-thead">
                        <tr className="border-b border-border-default bg-bg-surface text-left text-xs uppercase tracking-wide text-text-muted">
                          <th className="px-3 py-2 font-medium">Severity</th>
                          <th className="px-3 py-2 font-medium">Issue types</th>
                          <th className="px-3 py-2 font-medium">Identity</th>
                          <th className="px-3 py-2 font-medium">Canonical card</th>
                          <th className="px-3 py-2 font-medium">Release product</th>
                          <th className="px-3 py-2 font-medium">Rarity</th>
                          <th className="px-3 py-2 font-medium">Print treatment</th>
                          <th className="px-3 py-2 font-medium">Language</th>
                          <th className="px-3 py-2 font-medium">Suggested action</th>
                          <th className="px-3 py-2 font-medium">Links</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gapItems.map((item) => (
                          <tr
                            key={`${item.identity_scope}-${item.card_print_id ?? item.card_id}-${item.issue_types.join(",")}`}
                            className="border-b border-border-muted last:border-0 hover:bg-bg-elevated/60"
                          >
                            <td className="px-3 py-2">
                              <SeverityPill severity={item.severity} />
                            </td>
                            <td className="px-3 py-2 max-w-[14rem]">
                              <div className="flex flex-wrap gap-1">
                                {item.issue_types.map((t) => (
                                  <span key={t} className="rounded bg-bg-card px-1.5 py-0.5 text-[10px] text-text-secondary">
                                    {t}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              <div className="font-medium text-text-primary">{item.identity_scope === "physical_print" ? `CardPrint #${item.card_print_id}` : "Legacy compatibility Card"}</div>
                              {item.identity_scope === "physical_print" && <div className="text-xs text-text-muted">Exact physical print</div>}
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              <div>{formatNullable(item.card_code, (v) => v, NOT_AVAILABLE)} · {formatNullable(item.name_en ?? item.name_jp, (v) => v, NOT_AVAILABLE)}</div>
                              <div className="text-xs text-text-muted">Canonical Card #{item.canonical_card_id ?? item.card_id ?? "—"}</div>
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              {formatNullable(item.release_product_name ?? item.release_product_code ?? item.set_code, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              {formatNullable(item.rarity, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              {formatNullable(item.treatment ?? item.official_asset_variant ?? item.variant, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-text-secondary">
                              {formatNullable(item.language, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-xs text-text-muted">{item.suggested_action}</td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-2 text-xs">
                                {item.card_print_id !== null && <Link href={`/prints/${item.card_print_id}`} className="text-sky-400 hover:underline">Physical print</Link>}
                                {(item.compatibility_card_id ?? item.card_id) !== null && <Link href={`/cards/${item.compatibility_card_id ?? item.card_id}`} className="text-sky-400 hover:underline">Compatibility Card</Link>}
                                <Link href="/admin/cards" className="text-sky-400 hover:underline">
                                  Catalog
                                </Link>
                                <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:underline">
                                  Mappings
                                </Link>
                                <Link href="/admin/card-duplicates" className="text-sky-400 hover:underline">
                                  Duplicates
                                </Link>
                                <Link href="/admin/card-audit" className="text-sky-400 hover:underline">
                                  Audit
                                </Link>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableScrollContainer>
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
