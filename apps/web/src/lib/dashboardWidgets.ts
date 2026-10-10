import { DASHBOARD_WIDGET_IDS, type DashboardWidgetId } from "@/lib/api";

// Opportunities, market reports and signal events are admin-only data (GET
// /market/opportunities, /market/report*, /market/signal-events): the overview
// API always returns these widgets empty, so the dashboard neither renders
// them nor offers them in Customize.
const WITHHELD_WIDGET_IDS: ReadonlySet<string> = new Set([
  "top_opportunities",
  "market_report",
  "recent_signal_events",
]);

export function isShownWidget(id: string): id is DashboardWidgetId {
  return (DASHBOARD_WIDGET_IDS as readonly string[]).includes(id) && !WITHHELD_WIDGET_IDS.has(id);
}

export function buildFullOrder(layout: string[]): DashboardWidgetId[] {
  const seen = new Set(layout);
  const known = layout.filter(isShownWidget);
  const missing = DASHBOARD_WIDGET_IDS.filter((id) => !seen.has(id) && isShownWidget(id));
  return [...known, ...missing];
}
