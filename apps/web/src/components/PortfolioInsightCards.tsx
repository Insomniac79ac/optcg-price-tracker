import type {
  BestWorstPerformer,
  HighestValueItem,
  PortfolioValuationInsights,
  RetailLiquidationGap,
  ValuationBasis,
} from "@/lib/api";
import {
  cardDisplayName,
  formatJpy,
  formatSignedJpy,
  formatSignedPct,
} from "@/lib/format";

function basisLabel(basis: ValuationBasis): string {
  return basis === "market_floor" ? "SNKRDUNK floor" : "Yuyu-Tei sell";
}

interface PortfolioInsightCardsProps {
  insights: PortfolioValuationInsights | null;
}

export function PortfolioInsightCards({ insights }: PortfolioInsightCardsProps) {
  return (
    <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <InsightCard label="Best performer">
        {insights?.best_performing_item ? (
          <PerformerBody item={insights.best_performing_item} tone="positive" />
        ) : (
          <EmptyBody />
        )}
      </InsightCard>

      <InsightCard label="Worst performer">
        {insights?.worst_performing_item ? (
          <PerformerBody item={insights.worst_performing_item} tone="negative" />
        ) : (
          <EmptyBody />
        )}
      </InsightCard>

      <InsightCard label="Largest retail/liquidation spread">
        {insights?.largest_retail_liquidation_gap ? (
          <GapBody gap={insights.largest_retail_liquidation_gap} />
        ) : (
          <EmptyBody />
        )}
      </InsightCard>

      <InsightCard label="Highest value card">
        {insights?.highest_value_item ? (
          <HighestValueBody item={insights.highest_value_item} />
        ) : (
          <EmptyBody />
        )}
      </InsightCard>
    </div>
  );
}

function InsightCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function EmptyBody() {
  return (
    <div className="text-sm italic text-neutral-600">Not enough data yet</div>
  );
}

function PerformerBody({
  item,
  tone,
}: {
  item: BestWorstPerformer;
  tone: "positive" | "negative";
}) {
  const toneClass = tone === "positive" ? "text-emerald-400" : "text-rose-400";
  return (
    <div>
      <div className="truncate text-sm font-medium text-neutral-100">
        {item.card_code} — {cardDisplayName(item)}
      </div>
      <div className={`mt-0.5 text-lg font-semibold ${toneClass}`}>
        {formatSignedJpy(item.pnl_jpy)}
      </div>
      <div className="text-xs text-neutral-500">
        {formatSignedPct(item.pnl_pct)} · via {basisLabel(item.basis)}
      </div>
    </div>
  );
}

function GapBody({ gap }: { gap: RetailLiquidationGap }) {
  return (
    <div>
      <div className="truncate text-sm font-medium text-neutral-100">
        {gap.card_code} — {cardDisplayName(gap)}
      </div>
      <div className="mt-0.5 text-lg font-semibold text-neutral-100">
        {formatJpy(gap.gap_jpy)}
      </div>
      <div className="text-xs text-neutral-500">
        {formatSignedPct(gap.gap_pct)} spread
      </div>
    </div>
  );
}

function HighestValueBody({ item }: { item: HighestValueItem }) {
  return (
    <div>
      <div className="truncate text-sm font-medium text-neutral-100">
        {item.card_code} — {cardDisplayName(item)}
      </div>
      <div className="mt-0.5 text-lg font-semibold text-neutral-100">
        {formatJpy(item.value_jpy)}
      </div>
      <div className="text-xs text-neutral-500">
        via {basisLabel(item.basis)}
      </div>
    </div>
  );
}
