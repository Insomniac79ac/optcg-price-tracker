"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { RarityBadge } from "@/components/RarityBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  AdminAuthRequiredError,
  fetchPortfolioRisk,
  type PortfolioRisk,
  type PortfolioRiskBreakdown,
  type PortfolioRiskConcentration,
  type PortfolioRiskDataQuality,
  type PortfolioRiskDataQualityCard,
  type PortfolioRiskExposureItem,
  type PortfolioRiskExposures,
  type PortfolioRiskFlag,
  type PortfolioRiskGradingCard,
  type PortfolioRiskGradingExposure,
  type PortfolioRiskLevel,
  type PortfolioRiskLiquidityCard,
  type PortfolioRiskLiquidityProxy,
  type PortfolioRiskSummary,
  type PortfolioRiskWishlistCard,
  type PortfolioRiskWishlistOverlap,
} from "@/lib/api";
import {
  formatDate,
  formatDateTime,
  formatJPY,
  formatNullable,
  formatNumber,
  formatPercent,
  formatSignedJpy,
} from "@/lib/format";

type PageStatus = "loading" | "unauthorized" | "error" | "ready";
type ValuationMode = "raw_market" | "graded_adjusted";

const LEVEL_STYLES: Record<PortfolioRiskLevel, string> = {
  low: "text-emerald-400",
  medium: "text-amber-400",
  high: "text-orange-400",
  critical: "text-rose-400",
};

const EXPOSURE_TABS: { key: keyof PortfolioRiskExposures; label: string }[] = [
  { key: "by_set", label: "By set" },
  { key: "by_rarity", label: "By rarity" },
  { key: "by_variant", label: "By variant" },
  { key: "by_language", label: "By language" },
  { key: "by_tag", label: "By tag" },
  { key: "by_group", label: "By group" },
];

const BREAKDOWN_CARDS: { key: keyof PortfolioRiskBreakdown; title: string; anchor: string }[] = [
  { key: "concentration", title: "Concentration", anchor: "#concentration-details" },
  { key: "data_quality", title: "Data quality", anchor: "#data-quality-details" },
  { key: "liquidity_proxy", title: "Liquidity proxy", anchor: "#liquidity-details" },
  { key: "grading_exposure", title: "Grading exposure", anchor: "#grading-details" },
  { key: "wishlist_overlap", title: "Wishlist overlap", anchor: "#wishlist-overlap-details" },
];

export default function PortfolioRiskPage() {
  const [data, setData] = useState<PortfolioRisk | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");
  const [includeSold, setIncludeSold] = useState(false);
  const [exposureTab, setExposureTab] = useState<keyof PortfolioRiskExposures>("by_set");

  const load = useCallback(() => {
    setStatus("loading");
    fetchPortfolioRisk({ valuation_mode: valuationMode, include_sold: includeSold })
      .then((res) => {
        setData(res);
        setStatus("ready");
      })
      .catch((err) => {
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });
  }, [valuationMode, includeSold]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-100">Portfolio Risk</h1>
          <Link
            href="/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection →
          </Link>
          <Link
            href="/analytics/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection Analytics →
          </Link>
          <Link
            href="/analytics/digest"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Digest →
          </Link>
        </div>
        <p className="mb-1 text-sm text-neutral-500">
          Concentration, data quality, liquidity proxies, and grading exposure.
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

          <label className="flex items-center gap-2 text-xs text-neutral-400">
            <input
              type="checkbox"
              checked={includeSold}
              onChange={(e) => setIncludeSold(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-neutral-700 bg-neutral-900"
            />
            Include sold
          </label>
        </div>

        {status === "loading" && <LoadingState>Loading portfolio risk…</LoadingState>}
        {status === "unauthorized" && <ErrorState>Sign in to view portfolio risk.</ErrorState>}
        {status === "error" && <ErrorState>Failed to load portfolio risk from the API.</ErrorState>}

        {status === "ready" && data && (
          <>
            <SummaryCards summary={data.summary} />
            <RiskBreakdownSection breakdown={data.risk_breakdown} />
            <RecommendationFlagsSection flags={data.recommendation_flags} />
            <ExposuresSection exposures={data.exposures} tab={exposureTab} onTabChange={setExposureTab} />
            <ConcentrationDetails concentration={data.risk_breakdown.concentration} />
            <DataQualityDetails dataQuality={data.risk_breakdown.data_quality} />
            <LiquidityDetails liquidity={data.risk_breakdown.liquidity_proxy} />
            <GradingDetails grading={data.risk_breakdown.grading_exposure} />
            <WishlistOverlapDetails wishlistOverlap={data.risk_breakdown.wishlist_overlap} />
          </>
        )}
      </main>
    </div>
  );
}

function Section({
  title,
  children,
  id,
  last = false,
}: {
  title: string;
  children: React.ReactNode;
  id?: string;
  last?: boolean;
}) {
  return (
    <section id={id} className={`scroll-mt-16 ${last ? "mb-2" : "mb-8"}`}>
      <h2 className="mb-2 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "good" | "bad";
}) {
  const toneClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-amber-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function CardCell({ cardId, cardCode, nameEn }: { cardId: number; cardCode: string; nameEn: string | null }) {
  return (
    <>
      <Link href={`/cards/${cardId}`} className="text-sky-400 hover:text-sky-300">
        {cardCode}
      </Link>
      <div className="text-xs text-neutral-500">{nameEn || "Unknown card"}</div>
    </>
  );
}

function SummaryCards({ summary }: { summary: PortfolioRiskSummary }) {
  return (
    <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 sm:col-span-2">
        <div className="text-xs uppercase tracking-wide text-neutral-500">Risk score</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={`text-4xl font-bold ${LEVEL_STYLES[summary.risk_level]}`}>{summary.risk_score}</span>
          <span className={`text-sm font-semibold uppercase ${LEVEL_STYLES[summary.risk_level]}`}>
            {summary.risk_level}
          </span>
        </div>
      </div>
      <StatCard label="Total value" value={formatJPY(summary.total_value_jpy)} />
      <StatCard label="Largest single card weight" value={formatPercent(summary.largest_single_card_weight_pct)} />
      <StatCard label="Top 5 weight" value={formatPercent(summary.top_5_weight_pct)} />
      <StatCard label="Top 10 weight" value={formatPercent(summary.top_10_weight_pct)} />
      <StatCard label="Largest set weight" value={formatPercent(summary.largest_set_weight_pct)} />
      <StatCard label="Largest rarity weight" value={formatPercent(summary.largest_rarity_weight_pct)} />
      <StatCard
        label="Missing prices"
        value={formatNumber(summary.missing_price_count)}
        tone={summary.missing_price_count > 0 ? "bad" : undefined}
      />
      <StatCard
        label="Missing cost basis"
        value={formatNumber(summary.missing_cost_basis_count)}
        tone={summary.missing_cost_basis_count > 0 ? "bad" : undefined}
      />
      <StatCard
        label="Stale prices"
        value={formatNumber(summary.stale_price_count)}
        tone={summary.stale_price_count > 0 ? "bad" : undefined}
      />
      <StatCard
        label="Wide spread cards"
        value={formatNumber(summary.wide_spread_count)}
        tone={summary.wide_spread_count > 0 ? "bad" : undefined}
      />
      <StatCard label="Active grading" value={formatNumber(summary.active_grading_count)} />
      <StatCard
        label="Wishlist overlap"
        value={formatNumber(summary.wishlist_overlap_count)}
        tone={summary.wishlist_overlap_count > 0 ? "bad" : undefined}
      />
    </div>
  );
}

function RiskBreakdownSection({ breakdown }: { breakdown: PortfolioRiskBreakdown }) {
  return (
    <Section title="Risk breakdown">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {BREAKDOWN_CARDS.map(({ key, title, anchor }) => {
          const b = breakdown[key];
          return (
            <div key={key} className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="text-xs uppercase tracking-wide text-neutral-500">{title}</div>
                <span className={`text-xs font-semibold uppercase ${LEVEL_STYLES[b.level]}`}>{b.level}</span>
              </div>
              <div className={`mt-1 text-2xl font-semibold ${LEVEL_STYLES[b.level]}`}>{b.score}</div>
              {b.warnings.length > 0 ? (
                <ul className="mt-2 space-y-1 text-xs text-neutral-400">
                  {b.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-neutral-600">No warnings.</p>
              )}
              <Link
                href={anchor}
                className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                View details →
              </Link>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function RecommendationFlagsSection({ flags }: { flags: PortfolioRiskFlag[] }) {
  return (
    <Section title="Recommendation flags">
      {flags.length === 0 ? (
        <EmptyState variant="inline">No risk flags triggered.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Flag type</th>
                <th className="px-3 py-2">Message</th>
                <th className="px-3 py-2">Suggested action</th>
                <th className="px-3 py-2">Related cards</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {flags.map((f, i) => (
                <tr key={i}>
                  <td className="px-3 py-2">
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td className="px-3 py-2 text-neutral-300">{f.flag_type.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-neutral-300">{f.message}</td>
                  <td className="px-3 py-2 text-neutral-400">{f.suggested_action.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-neutral-400">
                    {f.related_cards.length === 0 ? "not available" : f.related_cards.join(", ")}
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

function ExposuresSection({
  exposures,
  tab,
  onTabChange,
}: {
  exposures: PortfolioRiskExposures;
  tab: keyof PortfolioRiskExposures;
  onTabChange: (tab: keyof PortfolioRiskExposures) => void;
}) {
  const rows = exposures[tab];
  return (
    <Section title="Exposures">
      <div className="mb-3 flex flex-wrap gap-1">
        {EXPOSURE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onTabChange(t.key)}
            className={`rounded px-2.5 py-1 text-xs ${
              tab === t.key
                ? "bg-sky-500/20 text-sky-300"
                : "bg-neutral-900 text-neutral-400 hover:text-neutral-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <EmptyState variant="inline">No exposure data.</EmptyState>
      ) : (
        <ExposureTable rows={rows} />
      )}
    </Section>
  );
}

function ExposureTable({ rows }: { rows: PortfolioRiskExposureItem[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="px-3 py-2">Label</th>
            <th className="px-3 py-2 text-right">Quantity</th>
            <th className="px-3 py-2 text-right">Value</th>
            <th className="px-3 py-2 text-right">Weight %</th>
            <th className="px-3 py-2 text-right">Cost basis</th>
            <th className="px-3 py-2 text-right">P/L</th>
            <th className="px-3 py-2">Risk flags</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-800">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="px-3 py-2 text-neutral-200">{r.label}</td>
              <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(r.quantity)}</td>
              <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(r.value_jpy)}</td>
              <td className="px-3 py-2 text-right text-neutral-300">{formatPercent(r.portfolio_weight_pct)}</td>
              <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(r.cost_basis_jpy)}</td>
              <td className="px-3 py-2 text-right">
                <span
                  className={
                    r.pnl_jpy > 0 ? "text-emerald-400" : r.pnl_jpy < 0 ? "text-amber-400" : "text-neutral-300"
                  }
                >
                  {formatSignedJpy(r.pnl_jpy)}
                </span>
              </td>
              <td className="px-3 py-2 text-neutral-400">
                {r.risk_flags.length === 0 ? "none" : r.risk_flags.join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConcentrationDetails({ concentration }: { concentration: PortfolioRiskConcentration }) {
  return (
    <Section title="Concentration details" id="concentration-details">
      {concentration.top_cards.length === 0 ? (
        <EmptyState variant="inline">No cards to show.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Card</th>
                <th className="px-3 py-2">Set</th>
                <th className="px-3 py-2">Rarity</th>
                <th className="px-3 py-2 text-right">Quantity</th>
                <th className="px-3 py-2 text-right">Value</th>
                <th className="px-3 py-2 text-right">Weight %</th>
                <th className="px-3 py-2 text-right">Cost basis</th>
                <th className="px-3 py-2">Warnings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {concentration.top_cards.map((c) => (
                <tr key={c.collection_item_id}>
                  <td className="px-3 py-2">
                    <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                  </td>
                  <td className="px-3 py-2 text-neutral-300">{c.set_code}</td>
                  <td className="px-3 py-2">
                    <RarityBadge rarity={c.rarity} />
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(c.quantity)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.value_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatPercent(c.portfolio_weight_pct)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.cost_basis_jpy)}</td>
                  <td className="px-3 py-2 text-neutral-400">
                    {c.warnings.length === 0 ? "none" : c.warnings.join(", ")}
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

function DataQualityTable({ title, rows }: { title: string; rows: PortfolioRiskDataQualityCard[] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
      {rows.length === 0 ? (
        <EmptyState variant="inline">None.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Card</th>
                <th className="px-3 py-2">Issue</th>
                <th className="px-3 py-2">Latest observed</th>
                <th className="px-3 py-2">Suggested action</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {rows.map((c) => (
                <tr key={c.collection_item_id}>
                  <td className="px-3 py-2">
                    <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                  </td>
                  <td className="px-3 py-2 text-neutral-300">{c.issue}</td>
                  <td className="px-3 py-2 text-neutral-400">{formatNullable(c.latest_observed_at, formatDateTime)}</td>
                  <td className="px-3 py-2 text-neutral-400">{c.suggested_action.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2">
                    <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DataQualityDetails({ dataQuality }: { dataQuality: PortfolioRiskDataQuality }) {
  return (
    <Section title="Data quality details" id="data-quality-details">
      <div className="space-y-6">
        <DataQualityTable title="Missing prices" rows={dataQuality.missing_prices} />
        <DataQualityTable title="Missing cost basis" rows={dataQuality.missing_cost_basis} />
        <DataQualityTable title="Stale prices" rows={dataQuality.stale_prices} />
      </div>
    </Section>
  );
}

function LiquidityTable({ title, rows }: { title: string; rows: PortfolioRiskLiquidityCard[] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
      {rows.length === 0 ? (
        <EmptyState variant="inline">None.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Card</th>
                <th className="px-3 py-2 text-right">Yuyu-Tei sell</th>
                <th className="px-3 py-2 text-right">Yuyu-Tei buy</th>
                <th className="px-3 py-2 text-right">Spread %</th>
                <th className="px-3 py-2 text-right">SNKRDUNK floor</th>
                <th className="px-3 py-2 text-right">Listing count</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {rows.map((c) => (
                <tr key={c.collection_item_id}>
                  <td className="px-3 py-2">
                    <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.yuyutei_sell_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.yuyutei_buy_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatPercent(c.spread_pct)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.snkrdunk_floor_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(c.listing_count)}</td>
                  <td className="px-3 py-2">
                    <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LiquidityDetails({ liquidity }: { liquidity: PortfolioRiskLiquidityProxy }) {
  return (
    <Section title="Liquidity proxy details" id="liquidity-details">
      <div className="space-y-6">
        <LiquidityTable title="Wide spread cards" rows={liquidity.wide_spread_cards} />
        <LiquidityTable title="Low listing cards" rows={liquidity.low_listing_cards} />
      </div>
    </Section>
  );
}

function GradingTable({ title, rows }: { title: string; rows: PortfolioRiskGradingCard[] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
      {rows.length === 0 ? (
        <EmptyState variant="inline">None.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Card</th>
                <th className="px-3 py-2">Grading company</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Cost basis</th>
                <th className="px-3 py-2 text-right">Grading cost</th>
                <th className="px-3 py-2">Expected return</th>
                <th className="px-3 py-2">Overdue</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {rows.map((c) => (
                <tr key={c.collection_item_id}>
                  <td className="px-3 py-2">
                    <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                  </td>
                  <td className="px-3 py-2 text-neutral-300">
                    {formatNullable(c.grading_company, (v) => v)}
                  </td>
                  <td className="px-3 py-2 text-neutral-300">
                    {formatNullable(c.submission_status, (v) => v.replace(/_/g, " "))}
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.cost_basis_jpy)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatJPY(c.grading_cost_jpy)}</td>
                  <td className="px-3 py-2 text-neutral-300">
                    {formatNullable(c.expected_return_date, formatDate)}
                  </td>
                  <td className="px-3 py-2">
                    {c.overdue ? (
                      <span className="text-rose-400">Yes</span>
                    ) : (
                      <span className="text-neutral-500">No</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Link href="/grading" className="text-sky-400 hover:text-sky-300">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GradingDetails({ grading }: { grading: PortfolioRiskGradingExposure }) {
  return (
    <Section title="Grading exposure details" id="grading-details">
      <div className="space-y-6">
        <GradingTable title="Active grading items" rows={grading.active_grading_items} />
        <GradingTable title="High cost pending items" rows={grading.high_cost_pending_items} />
      </div>
    </Section>
  );
}

function WishlistOverlapDetails({ wishlistOverlap }: { wishlistOverlap: PortfolioRiskWishlistOverlap }) {
  return (
    <Section title="Wishlist overlap details" id="wishlist-overlap-details" last>
      {wishlistOverlap.owned_wishlist_items.length === 0 ? (
        <EmptyState variant="inline">None.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-3 py-2">Card</th>
                <th className="px-3 py-2">Priority</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Owned qty</th>
                <th className="px-3 py-2 text-right">Desired qty</th>
                <th className="px-3 py-2">Suggested action</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {wishlistOverlap.owned_wishlist_items.map((w: PortfolioRiskWishlistCard) => (
                <tr key={w.wishlist_item_id}>
                  <td className="px-3 py-2">
                    <CardCell cardId={w.card_id} cardCode={w.card_code} nameEn={w.name_en} />
                  </td>
                  <td className="px-3 py-2 text-neutral-300">{w.wishlist_priority}</td>
                  <td className="px-3 py-2 text-neutral-300">{w.wishlist_status.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(w.owned_quantity)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{formatNumber(w.desired_quantity)}</td>
                  <td className="px-3 py-2 text-neutral-400">{w.suggested_action.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2">
                    <Link href="/wishlist" className="text-sky-400 hover:text-sky-300">
                      View →
                    </Link>
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
