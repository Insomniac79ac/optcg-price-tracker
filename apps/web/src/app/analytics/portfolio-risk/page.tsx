"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { RarityBadge } from "@/components/RarityBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { StatCard as SharedStatCard, type StatTone } from "@/components/ui/StatCard";
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

function riskTone(level: PortfolioRiskLevel): StatTone {
  if (level === "low") return "good";
  if (level === "high" || level === "critical") return "bad";
  return "neutral";
}

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
          <h1 className="text-lg font-semibold text-text-primary">Portfolio Risk</h1>
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
        <p className="mb-1 text-sm text-text-muted">
          Concentration, data quality, liquidity proxies, and grading exposure.
        </p>
        <p className="mb-4 text-xs text-text-faint">
          Risk score is deterministic from your tracker data and should be reviewed manually.
        </p>

        <div className="mb-6 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted">
              Valuation mode
            </label>
            <div className="flex overflow-hidden rounded border border-border-default text-xs">
              {(["raw_market", "graded_adjusted"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setValuationMode(mode)}
                  className={`px-2.5 py-1 ${
                    valuationMode === mode
                      ? "bg-sky-500/20 text-sky-300"
                      : "bg-bg-surface text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {mode === "raw_market" ? "Raw market" : "Graded adjusted"}
                </button>
              ))}
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={includeSold}
              onChange={(e) => setIncludeSold(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border-default bg-bg-surface"
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
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
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
  tone?: StatTone;
}) {
  return <SharedStatCard label={label} value={value} tone={tone} />;
}

function CardCell({ cardId, cardCode, nameEn }: { cardId: number; cardCode: string; nameEn: string | null }) {
  return (
    <>
      <Link href={`/cards/${cardId}`} className="text-sky-400 hover:text-sky-300">
        {cardCode}
      </Link>
      <div className="text-xs text-text-muted">{nameEn || "Unknown card"}</div>
    </>
  );
}

function SummaryCards({ summary }: { summary: PortfolioRiskSummary }) {
  return (
    <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <div className="panel px-4 py-3 sm:col-span-2">
        <div className="text-xs uppercase tracking-wide text-text-muted">Risk score</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={`mono tabular text-4xl font-bold ${riskTone(summary.risk_level) === "good" ? "price-positive" : riskTone(summary.risk_level) === "bad" ? "price-negative" : "text-text-primary"}`}>
            {summary.risk_score}
          </span>
          <RiskBadge level={summary.risk_level} />
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
            <div key={key} className="panel px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="text-xs uppercase tracking-wide text-text-muted">{title}</div>
                <RiskBadge level={b.level} />
              </div>
              <div
                className={`mono tabular mt-1 text-2xl font-semibold ${riskTone(b.level) === "good" ? "price-positive" : riskTone(b.level) === "bad" ? "price-negative" : "text-text-primary"}`}
              >
                {b.score}
              </div>
              {b.warnings.length > 0 ? (
                <ul className="mt-2 space-y-1 text-xs text-text-secondary">
                  {b.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-text-faint">No warnings.</p>
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
      <DataTableShell isEmpty={flags.length === 0} emptyLabel="No risk flags triggered.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Flag type</th>
              <th>Message</th>
              <th>Suggested action</th>
              <th>Related cards</th>
            </tr>
          </thead>
          <tbody>
            {flags.map((f, i) => (
              <tr key={i}>
                <td>
                  <SeverityBadge severity={f.severity} />
                </td>
                <td className="text-text-secondary">{f.flag_type.replace(/_/g, " ")}</td>
                <td className="text-text-secondary">{f.message}</td>
                <td className="text-text-secondary">{f.suggested_action.replace(/_/g, " ")}</td>
                <td className="text-text-secondary">
                  {f.related_cards.length === 0 ? "not available" : f.related_cards.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
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
                : "bg-bg-surface text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <ExposureTable rows={rows} />
    </Section>
  );
}

function ExposureTable({ rows }: { rows: PortfolioRiskExposureItem[] }) {
  return (
    <DataTableShell isEmpty={rows.length === 0} emptyLabel="No exposure data.">
      <table className="data-table">
        <thead>
          <tr>
            <th>Label</th>
            <th className="text-right">Quantity</th>
            <th className="text-right">Value</th>
            <th className="text-right">Weight %</th>
            <th className="text-right">Cost basis</th>
            <th className="text-right">P/L</th>
            <th>Risk flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="text-text-primary">{r.label}</td>
              <td className="mono tabular text-right text-text-secondary">{formatNumber(r.quantity)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatJPY(r.value_jpy)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatPercent(r.portfolio_weight_pct)}</td>
              <td className="mono tabular text-right text-text-secondary">{formatJPY(r.cost_basis_jpy)}</td>
              <td className="mono tabular text-right">
                <span className={r.pnl_jpy > 0 ? "price-positive" : r.pnl_jpy < 0 ? "price-negative" : "price-muted"}>
                  {formatSignedJpy(r.pnl_jpy)}
                </span>
              </td>
              <td className="text-text-secondary">
                {r.risk_flags.length === 0 ? "none" : r.risk_flags.join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </DataTableShell>
  );
}

function ConcentrationDetails({ concentration }: { concentration: PortfolioRiskConcentration }) {
  return (
    <Section title="Concentration details" id="concentration-details">
      <DataTableShell isEmpty={concentration.top_cards.length === 0} emptyLabel="No cards to show.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Card</th>
              <th>Set</th>
              <th>Rarity</th>
              <th className="text-right">Quantity</th>
              <th className="text-right">Value</th>
              <th className="text-right">Weight %</th>
              <th className="text-right">Cost basis</th>
              <th>Warnings</th>
            </tr>
          </thead>
          <tbody>
            {concentration.top_cards.map((c) => (
              <tr key={c.collection_item_id}>
                <td>
                  <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                </td>
                <td className="text-text-secondary">{c.set_code}</td>
                <td>
                  <RarityBadge rarity={c.rarity} />
                </td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(c.quantity)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.value_jpy)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatPercent(c.portfolio_weight_pct)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.cost_basis_jpy)}</td>
                <td className="text-text-secondary">
                  {c.warnings.length === 0 ? "none" : c.warnings.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
    </Section>
  );
}

function DataQualityTable({ title, rows }: { title: string; rows: PortfolioRiskDataQualityCard[] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</h3>
      <DataTableShell isEmpty={rows.length === 0} emptyLabel="None.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Card</th>
              <th>Issue</th>
              <th>Latest observed</th>
              <th>Suggested action</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.collection_item_id}>
                <td>
                  <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                </td>
                <td className="text-text-secondary">{c.issue}</td>
                <td className="mono tabular text-text-secondary">
                  {formatNullable(c.latest_observed_at, formatDateTime)}
                </td>
                <td className="text-text-secondary">{c.suggested_action.replace(/_/g, " ")}</td>
                <td>
                  <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
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
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</h3>
      <DataTableShell isEmpty={rows.length === 0} emptyLabel="None.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Card</th>
              <th className="text-right">Yuyu-Tei sell</th>
              <th className="text-right">Yuyu-Tei buy</th>
              <th className="text-right">Spread %</th>
              <th className="text-right">SNKRDUNK floor</th>
              <th className="text-right">Listing count</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.collection_item_id}>
                <td>
                  <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                </td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.yuyutei_sell_jpy)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.yuyutei_buy_jpy)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatPercent(c.spread_pct)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.snkrdunk_floor_jpy)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(c.listing_count)}</td>
                <td>
                  <Link href={`/cards/${c.card_id}`} className="text-sky-400 hover:text-sky-300">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
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
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</h3>
      <DataTableShell isEmpty={rows.length === 0} emptyLabel="None.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Card</th>
              <th>Grading company</th>
              <th>Status</th>
              <th className="text-right">Cost basis</th>
              <th className="text-right">Grading cost</th>
              <th>Expected return</th>
              <th>Overdue</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.collection_item_id}>
                <td>
                  <CardCell cardId={c.card_id} cardCode={c.card_code} nameEn={c.name_en} />
                </td>
                <td className="text-text-secondary">{formatNullable(c.grading_company, (v) => v)}</td>
                <td className="text-text-secondary">
                  {formatNullable(c.submission_status, (v) => v.replace(/_/g, " "))}
                </td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.cost_basis_jpy)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatJPY(c.grading_cost_jpy)}</td>
                <td className="mono tabular text-text-secondary">
                  {formatNullable(c.expected_return_date, formatDate)}
                </td>
                <td>
                  {c.overdue ? (
                    <span className="price-negative">Yes</span>
                  ) : (
                    <span className="text-text-muted">No</span>
                  )}
                </td>
                <td>
                  <Link href="/grading" className="text-sky-400 hover:text-sky-300">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
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
      <DataTableShell isEmpty={wishlistOverlap.owned_wishlist_items.length === 0} emptyLabel="None.">
        <table className="data-table">
          <thead>
            <tr>
              <th>Card</th>
              <th>Priority</th>
              <th>Status</th>
              <th className="text-right">Owned qty</th>
              <th className="text-right">Desired qty</th>
              <th>Suggested action</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {wishlistOverlap.owned_wishlist_items.map((w: PortfolioRiskWishlistCard) => (
              <tr key={w.wishlist_item_id}>
                <td>
                  <CardCell cardId={w.card_id} cardCode={w.card_code} nameEn={w.name_en} />
                </td>
                <td className="text-text-secondary">{w.wishlist_priority}</td>
                <td className="text-text-secondary">{w.wishlist_status.replace(/_/g, " ")}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(w.owned_quantity)}</td>
                <td className="mono tabular text-right text-text-secondary">{formatNumber(w.desired_quantity)}</td>
                <td className="text-text-secondary">{w.suggested_action.replace(/_/g, " ")}</td>
                <td>
                  <Link href="/wishlist" className="text-sky-400 hover:text-sky-300">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
    </Section>
  );
}
