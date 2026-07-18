"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { MarketSignalEventStatusBadge } from "@/components/MarketSignalEventStatusBadge";
import { MarketWorkflowRunStatusBadge } from "@/components/MarketWorkflowRunStatusBadge";
import { OpportunityCategoryBadge } from "@/components/OpportunityCategoryBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { WishlistPriorityBadge } from "@/components/WishlistPriorityBadge";
import {
  DASHBOARD_TIMEFRAMES,
  DASHBOARD_WIDGET_IDS,
  DEFAULT_DASHBOARD_PREFERENCES,
  type DashboardOverview,
  type DashboardTimeframe,
  type DashboardWidgetId,
  fetchDashboardOverview,
  updateDashboardPreferences,
} from "@/lib/api";
import {
  cardDisplayName,
  formatDate,
  formatDateTime,
  formatJpy,
  formatSignedJpy,
  formatSignedPct,
} from "@/lib/format";

// Dynamically imported (recharts is a sizeable chunk) so the rest of the
// dashboard's widgets don't pay for it just because this one widget exists.
// ssr: false sidesteps recharts' well-known SSR/hydration mismatch (it
// measures its container via ResizeObserver, which needs a real browser).
const DashboardPortfolioChart = dynamic(
  () =>
    import("@/components/DashboardPortfolioChart").then((mod) => mod.DashboardPortfolioChart),
  { ssr: false, loading: () => <LoadingState>Loading chart…</LoadingState> },
);

const WIDGET_LABELS: Record<DashboardWidgetId, string> = {
  portfolio_summary: "Portfolio summary",
  portfolio_chart: "Portfolio value over time",
  wishlist_targets: "Wishlist targets",
  top_opportunities: "Top opportunities",
  grading_status: "Grading status",
  market_report: "Latest market report",
  collection_quality: "Collection quality",
  recent_signal_events: "Recent signal events",
  data_freshness: "Data freshness",
  backup_status: "Backup status",
  workflow_status: "Workflow status",
};

const WIDGET_LINKS: Record<DashboardWidgetId, string> = {
  portfolio_summary: "/collection",
  portfolio_chart: "/collection",
  wishlist_targets: "/wishlist",
  top_opportunities: "/market/opportunities",
  grading_status: "/grading",
  market_report: "/market/report",
  collection_quality: "/collection",
  recent_signal_events: "/market/signal-events",
  data_freshness: "/admin/refresh-runs",
  backup_status: "/admin/backup",
  workflow_status: "/admin/market-workflow-runs",
};

function buildFullOrder(layout: string[]): DashboardWidgetId[] {
  const seen = new Set(layout);
  const known = layout.filter((id): id is DashboardWidgetId =>
    (DASHBOARD_WIDGET_IDS as readonly string[]).includes(id),
  );
  const missing = DASHBOARD_WIDGET_IDS.filter((id) => !seen.has(id));
  return [...known, ...missing];
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const [customizing, setCustomizing] = useState(false);
  const [draftOrder, setDraftOrder] = useState<DashboardWidgetId[]>([]);
  const [draftHidden, setDraftHidden] = useState<Set<string>>(new Set());
  const [draftTimeframe, setDraftTimeframe] = useState<DashboardTimeframe>("30d");
  const [draftBooleans, setDraftBooleans] = useState({
    show_raw_market_value: true,
    show_graded_adjusted_value: true,
    show_wishlist_budget: true,
    show_grading_costs: true,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  function refresh() {
    fetchDashboardOverview()
      .then((data) => {
        setOverview(data);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }

  useEffect(() => {
    refresh();
  }, []);

  function openCustomize() {
    if (!overview) return;
    const prefs = overview.preferences;
    setDraftOrder(buildFullOrder(prefs.layout));
    setDraftHidden(new Set(prefs.hidden_widgets));
    setDraftTimeframe((prefs.default_timeframe as DashboardTimeframe) || "30d");
    setDraftBooleans({
      show_raw_market_value: prefs.show_raw_market_value,
      show_graded_adjusted_value: prefs.show_graded_adjusted_value,
      show_wishlist_budget: prefs.show_wishlist_budget,
      show_grading_costs: prefs.show_grading_costs,
    });
    setSaveError(null);
    setCustomizing(true);
  }

  function moveWidget(id: DashboardWidgetId, direction: -1 | 1) {
    setDraftOrder((prev) => {
      const idx = prev.indexOf(id);
      const target = idx + direction;
      if (idx === -1 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }

  function toggleHidden(id: DashboardWidgetId) {
    setDraftHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function saveCustomization() {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateDashboardPreferences({
        layout: draftOrder,
        hidden_widgets: Array.from(draftHidden),
        default_timeframe: draftTimeframe,
        ...draftBooleans,
      });
      setOverview((prev) => (prev ? { ...prev, preferences: updated } : prev));
      refresh();
      setCustomizing(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save preferences.");
    } finally {
      setSaving(false);
    }
  }

  async function resetToDefaults() {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateDashboardPreferences({
        ...DEFAULT_DASHBOARD_PREFERENCES,
        default_timeframe: DEFAULT_DASHBOARD_PREFERENCES.default_timeframe as DashboardTimeframe,
      });
      setOverview((prev) => (prev ? { ...prev, preferences: updated } : prev));
      refresh();
      setCustomizing(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to reset preferences.");
    } finally {
      setSaving(false);
    }
  }

  const visibleWidgets = useMemo(() => {
    if (!overview) return [];
    const { layout, hidden_widgets } = overview.preferences;
    return layout.filter(
      (id): id is DashboardWidgetId =>
        (DASHBOARD_WIDGET_IDS as readonly string[]).includes(id) && !hidden_widgets.includes(id),
    );
  }, [overview]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Dashboard</h1>
          <button
            type="button"
            onClick={openCustomize}
            disabled={!overview}
            className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
          >
            Customize dashboard
          </button>
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Your collection, wishlist, grading, and market signals in one view.
        </p>

        <Link
          href="/search"
          className="mb-6 flex items-center justify-between rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-500 hover:border-neutral-600 hover:text-neutral-300"
        >
          <span>Search cards, collection, wishlist, notes, signals…</span>
          <span className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-600">
            Ctrl/Cmd+K
          </span>
        </Link>

        {status === "loading" && <LoadingState>Loading dashboard…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load the dashboard from the API.</ErrorState>
        )}

        {status === "ready" && overview && (
          <>
            {visibleWidgets.length === 0 && (
              <EmptyState>
                All widgets are hidden. Use &quot;Customize dashboard&quot; to show some.
              </EmptyState>
            )}

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {visibleWidgets.map((id) => (
                <div
                  key={id}
                  className={id === "portfolio_chart" ? "lg:col-span-2" : undefined}
                >
                  <WidgetRenderer id={id} overview={overview} />
                </div>
              ))}
            </div>
          </>
        )}
      </main>

      {customizing && overview && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4">
          <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-900 p-4 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-neutral-100">Customize dashboard</h3>
              <button
                onClick={() => setCustomizing(false)}
                className="text-xs text-neutral-500 hover:text-neutral-200"
              >
                ✕
              </button>
            </div>

            {saveError && (
              <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                {saveError}
              </div>
            )}

            <div className="mb-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                Widgets
              </div>
              <div className="space-y-1">
                {draftOrder.map((id, idx) => (
                  <div
                    key={id}
                    className="flex items-center justify-between rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5"
                  >
                    <label className="flex items-center gap-2 text-xs text-neutral-200">
                      <input
                        type="checkbox"
                        checked={!draftHidden.has(id)}
                        onChange={() => toggleHidden(id)}
                        className="rounded border-neutral-700 bg-neutral-950"
                      />
                      {WIDGET_LABELS[id]}
                    </label>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => moveWidget(id, -1)}
                        disabled={idx === 0}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-xs text-neutral-300 hover:text-neutral-100 disabled:opacity-30"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        onClick={() => moveWidget(id, 1)}
                        disabled={idx === draftOrder.length - 1}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-xs text-neutral-300 hover:text-neutral-100 disabled:opacity-30"
                      >
                        ↓
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex items-center gap-2 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={draftBooleans.show_raw_market_value}
                  onChange={(e) =>
                    setDraftBooleans((prev) => ({ ...prev, show_raw_market_value: e.target.checked }))
                  }
                  className="rounded border-neutral-700 bg-neutral-950"
                />
                Show raw market value
              </label>
              <label className="flex items-center gap-2 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={draftBooleans.show_graded_adjusted_value}
                  onChange={(e) =>
                    setDraftBooleans((prev) => ({
                      ...prev,
                      show_graded_adjusted_value: e.target.checked,
                    }))
                  }
                  className="rounded border-neutral-700 bg-neutral-950"
                />
                Show graded-adjusted value
              </label>
              <label className="flex items-center gap-2 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={draftBooleans.show_wishlist_budget}
                  onChange={(e) =>
                    setDraftBooleans((prev) => ({ ...prev, show_wishlist_budget: e.target.checked }))
                  }
                  className="rounded border-neutral-700 bg-neutral-950"
                />
                Show wishlist budget
              </label>
              <label className="flex items-center gap-2 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={draftBooleans.show_grading_costs}
                  onChange={(e) =>
                    setDraftBooleans((prev) => ({ ...prev, show_grading_costs: e.target.checked }))
                  }
                  className="rounded border-neutral-700 bg-neutral-950"
                />
                Show grading costs
              </label>
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2 text-xs text-neutral-400">
                Default timeframe
                <select
                  value={draftTimeframe}
                  onChange={(e) => setDraftTimeframe(e.target.value as DashboardTimeframe)}
                  className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100"
                >
                  {DASHBOARD_TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>
                      {tf}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={saveCustomization}
                disabled={saving}
                className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={resetToDefaults}
                disabled={saving}
                className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
              >
                Reset to defaults
              </button>
              <button
                type="button"
                onClick={() => setCustomizing(false)}
                disabled={saving}
                className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function WidgetCard({
  id,
  children,
}: {
  id: DashboardWidgetId;
  children: React.ReactNode;
}) {
  return (
    <section className="h-full rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-neutral-200">{WIDGET_LABELS[id]}</h2>
        <Link
          href={WIDGET_LINKS[id]}
          className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
        >
          View all →
        </Link>
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-neutral-100">{value}</div>
    </div>
  );
}

function WidgetRenderer({
  id,
  overview,
}: {
  id: DashboardWidgetId;
  overview: DashboardOverview;
}) {
  const { widgets, preferences } = overview;

  switch (id) {
    case "portfolio_summary": {
      const w = widgets.portfolio_summary;
      return (
        <WidgetCard id={id}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Cost basis" value={formatJpy(w.total_cost_basis_jpy)} />
            {preferences.show_raw_market_value && (
              <Stat label="Market floor value" value={formatJpy(w.market_floor_value_jpy)} />
            )}
            {preferences.show_graded_adjusted_value && (
              <Stat label="Graded-adjusted value" value={formatJpy(w.graded_adjusted_value_jpy)} />
            )}
            {preferences.show_raw_market_value && (
              <Stat
                label="P&L vs market floor"
                value={
                  <>
                    {formatSignedJpy(w.pnl_vs_market_floor_jpy)}{" "}
                    <span className="text-neutral-500">
                      ({formatSignedPct(w.pnl_vs_market_floor_pct)})
                    </span>
                  </>
                }
              />
            )}
            {preferences.show_graded_adjusted_value && (
              <Stat
                label="P&L vs graded-adjusted"
                value={
                  <>
                    {formatSignedJpy(w.pnl_vs_graded_adjusted_jpy)}{" "}
                    <span className="text-neutral-500">
                      ({formatSignedPct(w.pnl_vs_graded_adjusted_pct)})
                    </span>
                  </>
                }
              />
            )}
          </div>
        </WidgetCard>
      );
    }

    case "portfolio_chart": {
      const w = widgets.portfolio_chart;
      return (
        <WidgetCard id={id}>
          <DashboardPortfolioChart
            widget={w}
            showRawMarketValue={preferences.show_raw_market_value}
            showGradedAdjustedValue={preferences.show_graded_adjusted_value}
          />
        </WidgetCard>
      );
    }

    case "wishlist_targets": {
      const w = widgets.wishlist_targets;
      return (
        <WidgetCard id={id}>
          <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="High/grail targets hit" value={w.total_target_hit} />
            {preferences.show_wishlist_budget && (
              <>
                <Stat label="Target budget" value={formatJpy(w.total_target_budget_jpy)} />
                <Stat label="Max budget" value={formatJpy(w.total_max_budget_jpy)} />
              </>
            )}
          </div>
          {w.items.length === 0 ? (
            <EmptyState variant="inline">No wishlist targets hit yet</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {w.items.slice(0, 5).map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-2 text-xs text-neutral-300"
                >
                  <span className="flex items-center gap-1.5 truncate">
                    <WishlistPriorityBadge priority={item.priority} />
                    <Link href={`/cards/${item.card_id}`} className="truncate hover:text-sky-400">
                      {cardDisplayName(item)}
                    </Link>
                  </span>
                  <span className="whitespace-nowrap text-neutral-500">
                    {formatJpy(item.target_buy_price_jpy)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </WidgetCard>
      );
    }

    case "top_opportunities": {
      const w = widgets.top_opportunities;
      return (
        <WidgetCard id={id}>
          {w.opportunities.length === 0 ? (
            <EmptyState variant="inline">No ranked opportunities yet</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {w.opportunities.map((opp) => (
                <li
                  key={opp.event_id}
                  className="flex items-center justify-between gap-2 text-xs text-neutral-300"
                >
                  <span className="flex items-center gap-1.5 truncate">
                    <span className="font-semibold text-neutral-100">{opp.score}</span>
                    <OpportunityCategoryBadge category={opp.category} />
                    {opp.card_id !== null ? (
                      <Link href={`/cards/${opp.card_id}`} className="truncate hover:text-sky-400">
                        {cardDisplayName(opp)}
                      </Link>
                    ) : (
                      <span className="truncate text-neutral-500">{opp.signal_type}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </WidgetCard>
      );
    }

    case "grading_status": {
      const w = widgets.grading_status;
      return (
        <WidgetCard id={id}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Total submissions" value={w.total_submissions} />
            <Stat label="Submitted/grading" value={w.submitted_or_grading_count} />
            <Stat label="Received" value={w.received_count} />
            {preferences.show_grading_costs && (
              <Stat label="Total grading cost" value={formatJpy(w.total_grading_cost_jpy)} />
            )}
          </div>
        </WidgetCard>
      );
    }

    case "market_report": {
      const w = widgets.market_report;
      return (
        <WidgetCard id={id}>
          {w.report_id === null ? (
            <EmptyState variant="inline">No market report yet</EmptyState>
          ) : (
            <>
              <div className="mb-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Stat label="Report date" value={formatDate(w.report_date)} />
                <Stat label="Total opportunities" value={w.total_opportunities ?? "not available"} />
                <Stat label="Highest score" value={w.highest_score ?? "not available"} />
              </div>
              {w.deterministic_summary_lines.length > 0 && (
                <ul className="space-y-1 text-xs text-neutral-400">
                  {w.deterministic_summary_lines.map((line, idx) => (
                    <li key={idx}>• {line}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </WidgetCard>
      );
    }

    case "collection_quality": {
      const w = widgets.collection_quality;
      return (
        <WidgetCard id={id}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Missing purchase price" value={w.missing_purchase_price_count} />
            <Stat label="Missing condition" value={w.missing_condition_count} />
            <Stat label="Missing target sell" value={w.missing_target_sell_count} />
          </div>
        </WidgetCard>
      );
    }

    case "recent_signal_events": {
      const w = widgets.recent_signal_events;
      return (
        <WidgetCard id={id}>
          {w.events.length === 0 ? (
            <EmptyState variant="inline">No open or watched signal events</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {w.events.map((event) => (
                <li
                  key={event.id}
                  className="flex items-center justify-between gap-2 text-xs text-neutral-300"
                >
                  <span className="flex items-center gap-1.5 truncate">
                    <MarketSignalEventStatusBadge status={event.status} />
                    {event.card_id !== null ? (
                      <Link href={`/cards/${event.card_id}`} className="truncate hover:text-sky-400">
                        {cardDisplayName(event)}
                      </Link>
                    ) : (
                      <span className="truncate text-neutral-500">{event.signal_type}</span>
                    )}
                  </span>
                  <span className="whitespace-nowrap text-neutral-500">
                    {formatDateTime(event.last_seen_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </WidgetCard>
      );
    }

    case "data_freshness": {
      const w = widgets.data_freshness;
      return (
        <WidgetCard id={id}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Latest refresh" value={formatDateTime(w.latest_refresh_at)} />
            <Stat label="Refresh status" value={w.latest_refresh_status ?? "not available"} />
            <Stat label="Missing recent price" value={w.missing_recent_price_count} />
            <Stat label="Stale mapping price" value={w.stale_mapping_price_count} />
          </div>
        </WidgetCard>
      );
    }

    case "backup_status": {
      const w = widgets.backup_status;
      return (
        <WidgetCard id={id}>
          {w.tracked ? (
            <Stat label="Last backup" value={formatDateTime(w.last_backup_at)} />
          ) : (
            <EmptyState variant="inline">{w.message ?? "not available"}</EmptyState>
          )}
        </WidgetCard>
      );
    }

    case "workflow_status": {
      const w = widgets.workflow_status;
      const hasIssues = w.error_count_24h > 0 || w.warning_count_24h > 0;
      return (
        <WidgetCard id={id}>
          {w.run_id === null ? (
            <EmptyState variant="inline">No workflow runs yet</EmptyState>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat label="Run" value={`#${w.run_id}`} />
              <Stat label="Status" value={w.status ? <MarketWorkflowRunStatusBadge status={w.status} /> : "not available"} />
              <Stat label="Market report" value={w.market_report_id !== null ? `#${w.market_report_id}` : "not available"} />
              <Stat label="Telegram digest" value={w.telegram_digest_status ?? "not available"} />
              <Stat label="Finished" value={formatDateTime(w.finished_at)} />
            </div>
          )}
          {hasIssues && (
            <Link
              href="/admin/logs"
              className="mt-3 flex items-center gap-2 rounded border border-rose-900/50 bg-rose-950/30 px-2 py-1.5 text-xs text-rose-300 hover:bg-rose-950/50"
            >
              {w.error_count_24h > 0 && <span>{w.error_count_24h} error(s)</span>}
              {w.warning_count_24h > 0 && <span>{w.warning_count_24h} warning(s)</span>}
              <span className="text-rose-400">in the last 24h - view logs</span>
            </Link>
          )}
        </WidgetCard>
      );
    }

    default:
      return null;
  }
}
