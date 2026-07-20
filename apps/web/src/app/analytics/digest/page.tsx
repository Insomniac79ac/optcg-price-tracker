"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  AdminAuthRequiredError,
  AdminNotFoundError,
  fetchAnalyticsDigest,
  fetchAnalyticsDigestReport,
  fetchAnalyticsDigestReports,
  fetchLatestAnalyticsDigest,
  getAdminToken,
  triggerGenerateAnalyticsDigest,
  type AnalyticsDigest,
  type AnalyticsDigestPriorityItem,
  type AnalyticsDigestPriorityItems,
  type AnalyticsDigestReport,
  type AnalyticsDigestReportListResponse,
  type AnalyticsDigestSections,
} from "@/lib/api";
import { formatDateTime, formatJPY, formatNullable, formatNumber, formatPercent } from "@/lib/format";

type PageStatus = "loading" | "unauthorized" | "error" | "empty" | "ready";
type ValuationMode = "raw_market" | "graded_adjusted";
type DataMode = "live" | "latest";
type HistoryStatus = "loading" | "error" | "ready";

const LEVEL_STYLES: Record<string, string> = {
  low: "text-emerald-400",
  medium: "text-amber-400",
  high: "text-orange-400",
  critical: "text-rose-400",
};

const PRIORITY_SECTIONS: { key: keyof AnalyticsDigestPriorityItems; title: string }[] = [
  { key: "top_buy_decisions", title: "Top buy decisions" },
  { key: "top_sell_decisions", title: "Top sell decisions" },
  { key: "top_risk_flags", title: "Top risk flags" },
  { key: "wishlist_target_hits", title: "Wishlist target hits" },
  { key: "grading_overdue", title: "Overdue grading" },
  { key: "missing_data", title: "Missing data" },
];

export default function AnalyticsDigestPage() {
  const [dataMode, setDataMode] = useState<DataMode>("live");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");
  const [digest, setDigest] = useState<AnalyticsDigest | AnalyticsDigestReport | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");

  const [history, setHistory] = useState<AnalyticsDigestReportListResponse | null>(null);
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("loading");

  const [hasAdminToken, setHasAdminToken] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const loadDigest = useCallback(() => {
    setStatus("loading");
    const request =
      dataMode === "live"
        ? fetchAnalyticsDigest({ valuation_mode: valuationMode })
        : fetchLatestAnalyticsDigest({ valuation_mode: valuationMode });
    request
      .then((res) => {
        setDigest(res);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setStatus("unauthorized");
        else if (err instanceof AdminNotFoundError) setStatus("empty");
        else setStatus("error");
      });
  }, [dataMode, valuationMode]);

  const loadHistory = useCallback(() => {
    setHistoryStatus("loading");
    fetchAnalyticsDigestReports({ limit: 30 })
      .then((res) => {
        setHistory(res);
        setHistoryStatus("ready");
      })
      .catch(() => setHistoryStatus("error"));
  }, []);

  useEffect(() => {
    loadDigest();
  }, [loadDigest]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    setHasAdminToken(!!getAdminToken());
  }, []);

  function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    triggerGenerateAnalyticsDigest({ valuation_mode: valuationMode })
      .then(() => {
        loadDigest();
        loadHistory();
      })
      .catch((err) => {
        setGenerateError(err instanceof Error ? err.message : "Failed to generate digest.");
      })
      .finally(() => setGenerating(false));
  }

  function viewStoredReport(id: number) {
    setStatus("loading");
    fetchAnalyticsDigestReport(id)
      .then((res) => {
        setDigest(res);
        setStatus("ready");
        window.scrollTo({ top: 0, behavior: "smooth" });
      })
      .catch(() => setStatus("error"));
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex flex-wrap items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-100">Analytics Digest</h1>
          <Link href="/analytics/collection" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Collection →
          </Link>
          <Link href="/analytics/wishlist" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Wishlist →
          </Link>
          <Link href="/analytics/buy-decisions" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Buy decisions →
          </Link>
          <Link href="/analytics/sell-decisions" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Sell decisions →
          </Link>
          <Link href="/analytics/grading" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Grading →
          </Link>
          <Link href="/analytics/portfolio-risk" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
            Portfolio risk →
          </Link>
        </div>
        <p className="mb-1 text-sm text-neutral-500">
          Collection, wishlist, grading, buy/sell decisions, and portfolio risk in one view.
        </p>
        <p className="mb-4 text-xs text-neutral-600">
          Risk score is deterministic from your tracker data and should be reviewed manually.
        </p>

        <div className="mb-6 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500">
              Valuation mode
            </label>
            <div className="flex overflow-hidden rounded border border-neutral-700 text-xs">
              {(["raw_market", "graded_adjusted"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setValuationMode(mode)}
                  className={`px-2.5 py-1 ${
                    valuationMode === mode
                      ? "bg-sky-500/20 text-sky-300"
                      : "bg-neutral-900 text-neutral-400 hover:text-neutral-200"
                  }`}
                >
                  {mode === "raw_market" ? "Raw market" : "Graded adjusted"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500">
              Data source
            </label>
            <div className="flex overflow-hidden rounded border border-neutral-700 text-xs">
              {(["live", "latest"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setDataMode(mode)}
                  className={`px-2.5 py-1 ${
                    dataMode === mode
                      ? "bg-sky-500/20 text-sky-300"
                      : "bg-neutral-900 text-neutral-400 hover:text-neutral-200"
                  }`}
                >
                  {mode === "live" ? "Live calculation" : "Latest stored report"}
                </button>
              ))}
            </div>
          </div>

          {hasAdminToken && (
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating}
              className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate new digest"}
            </button>
          )}
        </div>
        {generateError && <p className="mb-4 text-xs text-rose-400">{generateError}</p>}

        {status === "loading" && <LoadingState>Loading analytics digest…</LoadingState>}
        {status === "unauthorized" && <ErrorState>Sign in to view the analytics digest.</ErrorState>}
        {status === "error" && <ErrorState>Failed to load the analytics digest from the API.</ErrorState>}
        {status === "empty" && (
          <EmptyState>
            No stored analytics digest yet. Generate one from /admin/actions, or switch to Live
            calculation above.
          </EmptyState>
        )}

        {status === "ready" && digest && (
          <>
            <SummaryCards digest={digest} />
            <DeterministicSummarySection lines={digest.deterministic_summary_lines} />
            <PriorityItemsSection priorityItems={digest.priority_items} />
            <SectionSummaries sections={digest.sections} />
          </>
        )}

        <DigestHistorySection status={historyStatus} history={history} onView={viewStoredReport} />
      </main>
    </div>
  );
}

function Section({
  title,
  children,
  last = false,
}: {
  title: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <section className={last ? "mb-2" : "mb-8"}>
      <h2 className="mb-2 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  tone,
  valueClassName,
}: {
  label: string;
  value: number | string;
  tone?: "good" | "bad";
  valueClassName?: string;
}) {
  const toneClass =
    valueClassName ?? (tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-amber-400" : "text-neutral-100");
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function SummaryCards({ digest }: { digest: AnalyticsDigest | AnalyticsDigestReport }) {
  const s = digest.summary;
  const levelClass = LEVEL_STYLES[s.portfolio_risk_level] ?? "text-neutral-100";
  return (
    <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatCard label="Collection value" value={formatJPY(s.collection_value_jpy)} />
      <StatCard label="Graded adjusted value" value={formatJPY(s.graded_adjusted_value_jpy)} />
      <StatCard label="Portfolio risk score" value={s.portfolio_risk_score} valueClassName={levelClass} />
      <StatCard
        label="Portfolio risk level"
        value={s.portfolio_risk_level}
        valueClassName={`uppercase ${levelClass}`}
      />
      <StatCard label="Wishlist target hits" value={formatNumber(s.wishlist_target_hits)} />
      <StatCard label="Buy review count" value={formatNumber(s.buy_review_count)} />
      <StatCard label="Sell review count" value={formatNumber(s.sell_review_count)} />
      <StatCard label="Grading ROI" value={formatJPY(s.grading_roi_jpy)} />
      <StatCard label="Active grading" value={formatNumber(s.grading_active_count)} />
      <StatCard
        label="Missing cost basis"
        value={formatNumber(s.missing_cost_basis_count)}
        tone={s.missing_cost_basis_count > 0 ? "bad" : undefined}
      />
      <StatCard
        label="Missing prices"
        value={formatNumber(s.missing_price_count)}
        tone={s.missing_price_count > 0 ? "bad" : undefined}
      />
    </div>
  );
}

function DeterministicSummarySection({ lines }: { lines: string[] }) {
  return (
    <Section title="Summary">
      {lines.length === 0 ? (
        <EmptyState variant="inline">No summary lines.</EmptyState>
      ) : (
        <ul className="list-disc space-y-1 rounded-lg border border-neutral-800 bg-neutral-900 px-8 py-4 text-sm text-neutral-300">
          {lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function PriorityItemsSection({ priorityItems }: { priorityItems: AnalyticsDigestPriorityItems }) {
  return (
    <Section title="Priority items">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {PRIORITY_SECTIONS.map(({ key, title }) => (
          <PriorityItemList key={key} title={title} items={priorityItems[key]} />
        ))}
      </div>
    </Section>
  );
}

function PriorityItemList({ title, items }: { title: string; items: AnalyticsDigestPriorityItem[] }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
      {items.length === 0 ? (
        <p className="text-xs text-neutral-600">None.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item, i) => (
            <li key={i} className="border-t border-neutral-800 pt-2 text-sm first:border-t-0 first:pt-0">
              <Link href={item.link} className="text-sky-400 hover:text-sky-300">
                {formatNullable(item.card_code, (v) => v)}
              </Link>
              {item.name_en && <span className="ml-1 text-xs text-neutral-500">{item.name_en}</span>}
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-neutral-400">
                {item.score !== null && <span>Score: {item.score}</span>}
                {item.risk_level !== null && <span>Risk: {item.risk_level}</span>}
                {item.severity !== null && <SeverityBadge severity={item.severity} />}
                <span>{item.message}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SectionCard({
  title,
  href,
  children,
}: {
  title: string;
  href: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
        <Link href={href} className="text-xs text-sky-400 hover:text-sky-300">
          View →
        </Link>
      </div>
      <dl className="space-y-1 text-sm text-neutral-300">{children}</dl>
    </div>
  );
}

function SectionRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-neutral-500">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function SectionSummaries({ sections }: { sections: AnalyticsDigestSections }) {
  return (
    <Section title="Section summaries">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <SectionCard title="Collection" href="/analytics/collection">
          <SectionRow label="Total items" value={formatNumber(sections.collection.total_items)} />
          <SectionRow label="Cost basis" value={formatJPY(sections.collection.total_cost_basis_jpy)} />
          <SectionRow label="Market value" value={formatJPY(sections.collection.raw_market_value_jpy)} />
          <SectionRow
            label="Largest set"
            value={sections.collection.largest_set_exposure?.label ?? "not available"}
          />
          <SectionRow
            label="Largest rarity"
            value={sections.collection.largest_rarity_exposure?.label ?? "not available"}
          />
        </SectionCard>

        <SectionCard title="Wishlist" href="/analytics/wishlist">
          <SectionRow label="Total items" value={formatNumber(sections.wishlist.total_items)} />
          <SectionRow label="Grails" value={formatNumber(sections.wishlist.grail_count)} />
          <SectionRow label="High priority" value={formatNumber(sections.wishlist.high_priority_count)} />
          <SectionRow label="Target hits" value={formatNumber(sections.wishlist.target_hit_count)} />
          <SectionRow label="Target budget" value={formatJPY(sections.wishlist.total_target_budget_jpy)} />
          <SectionRow label="Price coverage" value={formatPercent(sections.wishlist.price_coverage_pct)} />
        </SectionCard>

        <SectionCard title="Buy decisions" href="/analytics/buy-decisions">
          <SectionRow label="Review buy" value={formatNumber(sections.buy_decisions.review_buy_count)} />
          <SectionRow label="Wait" value={formatNumber(sections.buy_decisions.wait_count)} />
          <SectionRow label="Missing data" value={formatNumber(sections.buy_decisions.missing_data_count)} />
        </SectionCard>

        <SectionCard title="Sell decisions" href="/analytics/sell-decisions">
          <SectionRow label="Review sell" value={formatNumber(sections.sell_decisions.review_sell_count)} />
          <SectionRow label="Grade first" value={formatNumber(sections.sell_decisions.grade_first_count)} />
          <SectionRow label="Missing data" value={formatNumber(sections.sell_decisions.missing_data_count)} />
        </SectionCard>

        <SectionCard title="Grading" href="/analytics/grading">
          <SectionRow label="Active" value={formatNumber(sections.grading.active_submissions)} />
          <SectionRow label="Received" value={formatNumber(sections.grading.received_submissions)} />
          <SectionRow label="Grading cost" value={formatJPY(sections.grading.total_grading_cost_jpy)} />
          <SectionRow label="Graded value" value={formatJPY(sections.grading.total_graded_value_jpy)} />
          <SectionRow label="ROI" value={formatJPY(sections.grading.total_roi_jpy)} />
          <SectionRow label="Overdue" value={formatNumber(sections.grading.overdue_count)} />
        </SectionCard>

        <SectionCard title="Portfolio risk" href="/analytics/portfolio-risk">
          <SectionRow label="Risk score" value={String(sections.portfolio_risk.risk_score)} />
          <SectionRow label="Risk level" value={sections.portfolio_risk.risk_level} />
          <SectionRow label="Concentration" value={String(sections.portfolio_risk.concentration_score)} />
          <SectionRow label="Data quality" value={String(sections.portfolio_risk.data_quality_score)} />
          <SectionRow label="Liquidity proxy" value={String(sections.portfolio_risk.liquidity_proxy_score)} />
          <SectionRow label="Grading exposure" value={String(sections.portfolio_risk.grading_exposure_score)} />
          <SectionRow label="Wishlist overlap" value={String(sections.portfolio_risk.wishlist_overlap_score)} />
        </SectionCard>
      </div>
    </Section>
  );
}

function DigestHistorySection({
  status,
  history,
  onView,
}: {
  status: HistoryStatus;
  history: AnalyticsDigestReportListResponse | null;
  onView: (id: number) => void;
}) {
  return (
    <Section title="Digest history" last>
      {status === "loading" && <LoadingState>Loading digest history…</LoadingState>}
      {status === "error" && <ErrorState>Failed to load digest history.</ErrorState>}
      {status === "ready" && history && history.reports.length === 0 && (
        <EmptyState variant="inline">No stored digests yet.</EmptyState>
      )}
      {status === "ready" && history && history.reports.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Valuation mode</th>
                <th className="px-3 py-2 text-right">Collection value</th>
                <th className="px-3 py-2 text-right">Risk score</th>
                <th className="px-3 py-2">Risk level</th>
                <th className="px-3 py-2 text-right">Buy review</th>
                <th className="px-3 py-2 text-right">Sell review</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {history.reports.map((r) => (
                <tr key={r.id}>
                  <td className="px-3 py-2 text-neutral-300">{formatDateTime(r.created_at)}</td>
                  <td className="px-3 py-2 text-neutral-300">{r.valuation_mode}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(r.collection_value_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {formatNullable(r.portfolio_risk_score, (v) => String(v))}
                  </td>
                  <td className="px-3 py-2 text-neutral-300">
                    {formatNullable(r.portfolio_risk_level, (v) => v)}
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(r.buy_review_count)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(r.sell_review_count)}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => onView(r.id)}
                      className="text-sky-400 hover:text-sky-300"
                    >
                      View →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
