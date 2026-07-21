"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import {
  AdminAuthRequiredError,
  type CatalogCoverageBreakdownItem,
  type CatalogCoverageGapItem,
  type CatalogCoverageGapType,
  type CatalogCoverageReport,
  fetchCatalogCoverage,
  fetchCatalogCoverageGaps,
} from "@/lib/api";
import { formatNullable, formatNumber, formatPercent } from "@/lib/format";

const NOT_AVAILABLE = "not available";

const GAP_TABS: { value: CatalogCoverageGapType; label: string; emptyLabel: string }[] = [
  { value: "metadata", label: "Metadata gaps", emptyLabel: "No metadata gaps found" },
  { value: "mapping", label: "Mapping gaps", emptyLabel: "No mapping gaps found" },
  { value: "price", label: "Price gaps", emptyLabel: "No price gaps found" },
  { value: "duplicate", label: "Duplicate risks", emptyLabel: "No duplicate risks found" },
  { value: "mapping_quality", label: "Mapping quality risks", emptyLabel: "No mapping quality risks found" },
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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

const BREAKDOWN_LIMIT_OPTIONS = [10, 25, 50] as const;

function BreakdownTable({ title, items }: { title: string; items: CatalogCoverageBreakdownItem[] }) {
  const [visible, setVisible] = useState(25);

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
      <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-2">
        <span className="text-sm font-medium text-neutral-300">{title}</span>
        {items.length > BREAKDOWN_LIMIT_OPTIONS[0] && (
          <select
            value={visible}
            onChange={(e) => setVisible(Number(e.target.value))}
            className="rounded border border-neutral-700 bg-neutral-950 px-1.5 py-0.5 text-xs text-neutral-300"
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
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-xs uppercase tracking-wide text-neutral-500">
              <th className="px-3 py-2 font-medium">Label</th>
              <th className="px-3 py-2 text-right font-medium">Total</th>
              <th className="px-3 py-2 text-right font-medium">Mapped</th>
              <th className="px-3 py-2 text-right font-medium">Unmapped</th>
              <th className="px-3 py-2 text-right font-medium">Recent price</th>
              <th className="px-3 py-2 text-right font-medium">Collection</th>
              <th className="px-3 py-2 text-right font-medium">Wishlist</th>
              <th className="px-3 py-2 text-right font-medium">Missing metadata</th>
              <th className="px-3 py-2 text-right font-medium">Dup. risk</th>
              <th className="px-3 py-2 text-right font-medium">Mapping risk</th>
              <th className="px-3 py-2 text-right font-medium">Mapping %</th>
              <th className="px-3 py-2 text-right font-medium">Price %</th>
              <th className="px-3 py-2 text-right font-medium">Metadata %</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, visible).map((item) => (
              <tr key={item.key} className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
                <td className="px-3 py-2 font-medium text-neutral-200">{item.label}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.total_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.mapped_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.unmapped_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.recent_price_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.collection_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.wishlist_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.missing_metadata_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.duplicate_risk_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatNumber(item.mapping_quality_risk_cards)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatPercent(item.mapping_coverage_pct)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatPercent(item.recent_price_coverage_pct)}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{formatPercent(item.metadata_completion_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

  const [activeTab, setActiveTab] = useState<CatalogCoverageGapType>("metadata");
  const [severity, setSeverity] = useState("");
  const [gapItems, setGapItems] = useState<CatalogCoverageGapItem[]>([]);
  const [gapTotal, setGapTotal] = useState(0);
  const [gapStatus, setGapStatus] = useState<"loading" | "error" | "ready">("loading");
  const [gapLimit, setGapLimit] = useState(50);
  const [gapOffset, setGapOffset] = useState(0);

  useEffect(() => {
    let cancelled = false;
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
    setGapOffset(0);
  }, [activeTab, severity, setCode, rarity, variant, language]);

  useEffect(() => {
    let cancelled = false;
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
        { label: "Total cards", value: formatNumber(summary.total_cards) },
        { label: "Active cards", value: formatNumber(summary.active_cards) },
        { label: "Sets", value: formatNumber(summary.sets_count) },
        { label: "Yuyu-Tei mapped", value: formatNumber(summary.cards_with_yuyutei_mapping) },
        { label: "SNKRDUNK mapped", value: formatNumber(summary.cards_with_snkrdunk_mapping) },
        { label: "Without mapping", value: formatNumber(summary.cards_without_any_mapping) },
        { label: "Recent Yuyu-Tei prices", value: formatNumber(summary.cards_with_recent_yuyutei_price) },
        { label: "Recent SNKRDUNK prices", value: formatNumber(summary.cards_with_recent_snkrdunk_price) },
        { label: "Without recent price", value: formatNumber(summary.cards_without_recent_price) },
        { label: "In collection", value: formatNumber(summary.cards_in_collection) },
        { label: "On wishlist", value: formatNumber(summary.cards_on_wishlist) },
        { label: "Missing metadata", value: formatNumber(summary.cards_with_missing_metadata) },
        { label: "Duplicate risk", value: formatNumber(summary.cards_with_duplicate_risk) },
        { label: "Mapping quality risk", value: formatNumber(summary.cards_with_mapping_quality_risk) },
        { label: "Metadata completion", value: formatPercent(summary.metadata_completion_pct) },
        { label: "Mapping coverage", value: formatPercent(summary.mapping_coverage_pct) },
        { label: "Recent price coverage", value: formatPercent(summary.recent_price_coverage_pct) },
      ]
    : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex flex-wrap items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-100">Catalog Coverage</h1>
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
          <Link href="/admin/system-check" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            System check →
          </Link>
          <span className="ml-auto">
            <AdminLogoutButton />
          </span>
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Track canonical card coverage, metadata gaps, mappings, prices, and quality risks.
        </p>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2">
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
                  checked={includeInactive}
                  onChange={(e) => setIncludeInactive(e.target.checked)}
                />
                Include inactive
              </label>
            </div>

            {status === "loading" && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                Loading catalog coverage…
              </div>
            )}
            {status === "error" && (
              <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load catalog coverage from the API. Is the backend running?
              </div>
            )}

            {status === "ready" && report && (
              <>
                <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
                  {summaryCards.map((c) => (
                    <StatCard key={c.label} label={c.label} value={c.value} />
                  ))}
                </div>

                <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <BreakdownTable title="Coverage by set" items={report.coverage_by_set} />
                  <BreakdownTable title="Coverage by rarity" items={report.coverage_by_rarity} />
                  <BreakdownTable title="Coverage by variant" items={report.coverage_by_variant} />
                  <BreakdownTable title="Coverage by language" items={report.coverage_by_language} />
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
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                    className="ml-auto rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
                  >
                    {SEVERITY_OPTIONS.map((v) => (
                      <option key={v} value={v}>
                        {v || "Any severity"}
                      </option>
                    ))}
                  </select>
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
                    <table className="w-full min-w-[900px] border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                          <th className="px-3 py-2 font-medium">Severity</th>
                          <th className="px-3 py-2 font-medium">Issue types</th>
                          <th className="px-3 py-2 font-medium">Card code</th>
                          <th className="px-3 py-2 font-medium">Name</th>
                          <th className="px-3 py-2 font-medium">Set</th>
                          <th className="px-3 py-2 font-medium">Rarity</th>
                          <th className="px-3 py-2 font-medium">Variant</th>
                          <th className="px-3 py-2 font-medium">Language</th>
                          <th className="px-3 py-2 font-medium">Suggested action</th>
                          <th className="px-3 py-2 font-medium">Links</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gapItems.map((item) => (
                          <tr
                            key={`${item.card_id}-${item.issue_types.join(",")}`}
                            className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                          >
                            <td className="px-3 py-2">
                              <SeverityPill severity={item.severity} />
                            </td>
                            <td className="px-3 py-2 max-w-[14rem]">
                              <div className="flex flex-wrap gap-1">
                                {item.issue_types.map((t) => (
                                  <span key={t} className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                                    {t}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs text-neutral-300">
                              {formatNullable(item.card_code, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-neutral-300">
                              {formatNullable(item.name_en ?? item.name_jp, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-neutral-400">
                              {formatNullable(item.set_code, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-neutral-400">
                              {formatNullable(item.rarity, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-neutral-400">
                              {formatNullable(item.variant, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-neutral-400">
                              {formatNullable(item.language, (v) => v, NOT_AVAILABLE)}
                            </td>
                            <td className="px-3 py-2 text-xs text-neutral-500">{item.suggested_action}</td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-2 text-xs">
                                <Link href={`/cards/${item.card_id}`} className="text-sky-400 hover:underline">
                                  Card
                                </Link>
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
