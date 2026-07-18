"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { OpportunityCategoryBadge } from "@/components/OpportunityCategoryBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  AdminNotFoundError,
  type MarketIntelligenceReport,
  type MarketIntelligenceReportSummary,
  type MarketOpportunity,
  fetchLatestMarketReport,
  fetchMarketReport,
  fetchMarketReports,
} from "@/lib/api";
import {
  formatDateTime,
  formatDate,
  formatJPY as reportJpy,
  formatSignedJpy,
  formatPercent as reportPct,
  formatNumber as reportNumber,
} from "@/lib/format";

type Status = "loading" | "error" | "empty" | "ready";

const NA = "not available";

function reportSignedJpy(value: number | null | undefined): string {
  const formatted = formatSignedJpy(value);
  return formatted === "—" ? NA : formatted;
}

function reportText(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return NA;
  return value.replaceAll("_", " ");
}

function opportunityCardName(opp: MarketOpportunity): string {
  if (opp.card_id === null) return NA;
  return opp.name_en || opp.name_jp || NA;
}

export default function MarketReportPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [report, setReport] = useState<MarketIntelligenceReport | null>(null);
  const [reportsList, setReportsList] = useState<MarketIntelligenceReportSummary[]>([]);
  const [selectedValue, setSelectedValue] = useState<string>("latest");
  const [selectorError, setSelectorError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setStatus("loading");
    fetchLatestMarketReport()
      .then((data) => {
        if (cancelled) return;
        setReport(data);
        setSelectedValue("latest");
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus(err instanceof AdminNotFoundError ? "empty" : "error");
      });

    fetchMarketReports({ limit: 30 })
      .then((data) => {
        if (cancelled) return;
        setReportsList(data.reports);
      })
      .catch(() => {
        if (cancelled) return;
        setReportsList([]);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSelectReport(value: string) {
    setSelectorError(null);
    setSelectedValue(value);

    if (value === "latest") {
      try {
        const data = await fetchLatestMarketReport();
        setReport(data);
        setStatus("ready");
      } catch (err) {
        if (err instanceof AdminNotFoundError) {
          setStatus("empty");
        } else {
          setSelectorError("Failed to load the latest report.");
        }
      }
      return;
    }

    const reportId = Number(value);
    try {
      const data = await fetchMarketReport(reportId);
      setReport(data);
      setStatus("ready");
    } catch {
      setSelectorError(`Failed to load report #${reportId}.`);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Market Intelligence Report
            </h1>
            <Link
              href="/admin/actions"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Generate new report
            </Link>
            <Link
              href="/admin/market-workflow-runs"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Workflow runs
            </Link>
          </div>
          {reportsList.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-neutral-500">
              Previous reports
              <select
                value={selectedValue}
                onChange={(e) => handleSelectReport(e.target.value)}
                className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
              >
                <option value="latest">Latest</option>
                {reportsList.map((r) => (
                  <option key={r.id} value={String(r.id)}>
                    {formatDate(r.report_date)} · {formatDateTime(r.created_at)} · {r.total_opportunities} opp · high {reportNumber(r.highest_score)}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        <p className="mb-4 text-xs text-neutral-500">
          Reports update after successful price refreshes.
        </p>

        {selectorError && (
          <div className="mb-4 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {selectorError}
          </div>
        )}

        {status === "loading" && <LoadingState>Loading market report…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load the market report from the API.</ErrorState>
        )}

        {status === "empty" && (
          <EmptyState>
            <p>No market report generated yet</p>
            <p className="mt-2 text-xs text-neutral-600">
              Generate a report after your next successful price refresh or run
              python -m app.generate_market_report
            </p>
          </EmptyState>
        )}

        {status === "ready" && report && <ReportView report={report} />}
      </main>
    </div>
  );
}

function ReportView({ report }: { report: MarketIntelligenceReport }) {
  const cat = report.opportunity_summary.by_category;
  const top = report.top_opportunities;

  return (
    <div className="flex flex-col gap-6">
      <div className="text-xs text-neutral-500">
        Report date: <span className="text-neutral-300">{formatDate(report.report_date)}</span>
        {" · "}
        Generated: <span className="text-neutral-300">{formatDateTime(report.created_at)}</span>
      </div>

      <section>
        <SectionTitle>Summary</SectionTitle>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-9">
          <StatCard label="Total opportunities" value={reportNumber(report.opportunity_summary.total_opportunities)} />
          <StatCard label="Highest score" value={reportNumber(report.opportunity_summary.highest_score)} />
          <StatCard label="Average score" value={reportNumber(report.opportunity_summary.average_score)} />
          <StatCard label="Buy" value={reportNumber(cat.buy ?? 0)} />
          <StatCard label="Sell" value={reportNumber(cat.sell ?? 0)} />
          <StatCard label="Momentum" value={reportNumber(cat.momentum ?? 0)} />
          <StatCard label="Drops" value={reportNumber(cat.drop ?? 0)} />
          <StatCard label="Data quality" value={reportNumber(cat.data_quality ?? 0)} />
          <StatCard label="Owned" value={reportNumber(cat.owned ?? 0)} />
          <StatCard
            label="Wishlist target hit"
            value={reportNumber(report.opportunity_summary.wishlist_target_hit_count)}
          />
        </div>
      </section>

      <section>
        <SectionTitle>Portfolio snapshot</SectionTitle>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total cost basis" value={reportJpy(report.portfolio_snapshot.total_cost_basis_jpy)} />
          <StatCard label="Yuyu-Tei retail value" value={reportJpy(report.portfolio_snapshot.retail_value_jpy)} />
          <StatCard label="Yuyu-Tei liquidation value" value={reportJpy(report.portfolio_snapshot.liquidation_value_jpy)} />
          <StatCard label="SNKRDUNK market floor value" value={reportJpy(report.portfolio_snapshot.market_floor_value_jpy)} />
          <StatCard label="P/L vs market floor" value={reportSignedJpy(report.portfolio_snapshot.pnl_vs_market_floor_jpy)} />
          <StatCard label="P/L vs market floor %" value={reportPct(report.portfolio_snapshot.pnl_vs_market_floor_pct)} />
          <StatCard label="Items missing cost basis" value={reportNumber(report.portfolio_snapshot.items_missing_cost_basis)} />
          <StatCard label="Items missing prices" value={reportNumber(report.portfolio_snapshot.items_missing_prices)} />
          <StatCard label="Graded-adjusted value" value={reportJpy(report.portfolio_snapshot.graded_adjusted_value_jpy)} />
        </div>
      </section>

      <section>
        <SectionTitle>Deterministic summary</SectionTitle>
        {report.deterministic_summary_lines.length === 0 ? (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm text-neutral-500">
            {NA}
          </div>
        ) : (
          <ul className="list-disc space-y-1 rounded-lg border border-neutral-800 bg-neutral-900 p-4 pl-8 text-sm text-neutral-300">
            {report.deterministic_summary_lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <SectionTitle>Top opportunities</SectionTitle>

        <div className="mb-3 overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                <th className="px-2 py-1.5 font-medium">Score</th>
                <th className="px-2 py-1.5 font-medium">Category</th>
                <th className="px-2 py-1.5 font-medium">Code</th>
                <th className="px-2 py-1.5 font-medium">Name</th>
                <th className="px-2 py-1.5 font-medium">Message</th>
                <th className="px-2 py-1.5 font-medium">Suggested action</th>
                <th className="px-2 py-1.5 font-medium">Seen</th>
                <th className="px-2 py-1.5 font-medium">Links</th>
              </tr>
            </thead>
            <tbody>
              {top.top_5.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-2 py-4 text-center text-neutral-500">
                    {NA}
                  </td>
                </tr>
              ) : (
                top.top_5.map((opp) => <OpportunityRow key={opp.event_id} opp={opp} />)
              )}
            </tbody>
          </table>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <OpportunityCard label="Top buy" opp={top.top_buy} />
          <OpportunityCard label="Top sell" opp={top.top_sell} />
          <OpportunityCard label="Top momentum" opp={top.top_momentum} />
          <OpportunityCard label="Top drop" opp={top.top_drop} />
          <OpportunityCard label="Top owned" opp={top.top_owned} />
          <OpportunityCard label="Top data quality" opp={top.top_data_quality} />
        </div>
      </section>

      <section>
        <SectionTitle>Collection quality</SectionTitle>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Missing purchase price"
            value={reportNumber(report.collection_quality.missing_purchase_price_count)}
          />
          <StatCard
            label="Missing condition"
            value={reportNumber(report.collection_quality.missing_condition_count)}
          />
          <StatCard
            label="Missing target sell"
            value={reportNumber(report.collection_quality.missing_target_sell_count)}
          />
          <StatCard
            label="Total quality issues"
            value={reportNumber(report.collection_quality.total_quality_issues)}
          />
        </div>
        <Link
          href="/collection"
          className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
        >
          View collection
        </Link>
      </section>

      <section>
        <SectionTitle>Signal event summary</SectionTitle>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Open" value={reportNumber(report.signal_event_summary.open_events)} />
          <StatCard label="Watching" value={reportNumber(report.signal_event_summary.watching_events)} />
          <StatCard label="Dismissed" value={reportNumber(report.signal_event_summary.dismissed_events)} />
          <StatCard label="Resolved" value={reportNumber(report.signal_event_summary.resolved_events)} />
          <StatCard
            label="Most common signal type"
            value={reportText(report.signal_event_summary.most_common_signal_type)}
            wrap
          />
          <StatCard
            label="Most common suggested action"
            value={reportText(report.signal_event_summary.most_common_suggested_action)}
            wrap
          />
        </div>
        <Link
          href="/market/signal-events"
          className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
        >
          View signal events
        </Link>
      </section>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-sm font-semibold text-neutral-200">{children}</h2>
  );
}

function StatCard({
  label,
  value,
  wrap = false,
}: {
  label: string;
  value: string;
  wrap?: boolean;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div
        className={
          wrap
            ? "mt-1 break-words text-sm font-semibold leading-snug text-neutral-100"
            : "mt-1 truncate text-xl font-semibold text-neutral-100"
        }
      >
        {value}
      </div>
    </div>
  );
}

function OpportunityRow({ opp }: { opp: MarketOpportunity }) {
  return (
    <tr className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
      <td className="px-2 py-1.5 text-base font-bold text-neutral-100">{opp.score}</td>
      <td className="px-2 py-1.5">
        <OpportunityCategoryBadge category={opp.category} />
      </td>
      <td className="px-2 py-1.5 font-mono text-neutral-400">
        {opp.card_id !== null ? (
          <Link href={`/cards/${opp.card_id}`} className="hover:text-sky-400">
            {opp.card_code ?? NA}
          </Link>
        ) : (
          NA
        )}
      </td>
      <td className="px-2 py-1.5 font-medium text-neutral-100">{opportunityCardName(opp)}</td>
      <td className="max-w-[16rem] px-2 py-1.5 text-neutral-400">{opp.message ?? NA}</td>
      <td className="px-2 py-1.5 text-neutral-400">{reportText(opp.suggested_action)}</td>
      <td className="px-2 py-1.5 text-neutral-300">{opp.seen_count}</td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap gap-2">
          {opp.card_id !== null && (
            <Link
              href={`/cards/${opp.card_id}`}
              className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
            >
              Card
            </Link>
          )}
          <Link
            href="/market/opportunities"
            className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
          >
            Opportunities
          </Link>
          <Link
            href="/market/signal-events"
            className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
          >
            Event
          </Link>
        </div>
      </td>
    </tr>
  );
}

function OpportunityCard({ label, opp }: { label: string; opp: MarketOpportunity | null }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
        {opp && (
          <span className="text-lg font-bold text-neutral-100">{opp.score}</span>
        )}
      </div>

      {!opp ? (
        <div className="text-sm text-neutral-500">{NA}</div>
      ) : (
        <div className="flex flex-col gap-1 text-sm">
          <div className="flex items-center gap-2">
            <OpportunityCategoryBadge category={opp.category} />
            <span className="font-mono text-xs text-neutral-400">
              {opp.card_id !== null ? (
                <Link href={`/cards/${opp.card_id}`} className="hover:text-sky-400">
                  {opp.card_code ?? NA}
                </Link>
              ) : (
                NA
              )}
            </span>
          </div>
          <div className="font-medium text-neutral-100">{opportunityCardName(opp)}</div>
          <div className="text-xs text-neutral-400">{opp.message ?? NA}</div>
          <div className="text-xs text-neutral-500">
            Suggested action: {reportText(opp.suggested_action)}
          </div>
          <div className="text-xs text-neutral-500">Seen: {opp.seen_count}</div>
          <div className="mt-1 flex flex-wrap gap-2">
            {opp.card_id !== null && (
              <Link
                href={`/cards/${opp.card_id}`}
                className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
              >
                Card
              </Link>
            )}
            <Link
              href="/market/opportunities"
              className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
            >
              Opportunities
            </Link>
            <Link
              href="/market/signal-events"
              className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
            >
              Event
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
