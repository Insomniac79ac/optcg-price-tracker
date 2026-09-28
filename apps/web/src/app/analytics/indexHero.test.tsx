/** Legacy CPI hero remains reusable, but is no longer the Market page. */
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CardPirateIndexHero } from "@/components/ui/CardPirateIndexHero";
import type { IndexPoint, IndexSeries, IndexWindowRow } from "@/lib/cardPirateIndex";
function point(partial: Partial<IndexPoint> & { date: string; value: string }): IndexPoint {
  return {
    is_base: false,
    prior_point_date: null,
    step_days: 1,
    chain_link_log_return: null,
    constituent_count: 296,
    eligible_print_count: 305,
    movers_up: 0,
    movers_down: 0,
    movers_flat: 296,
    capped_count: 0,
    ...partial,
  };
}

/** Staging's own series on 2026-09-07: five days, a +0.01 % total move, and a
 * high that is nearly a whole point above where it ended. */
const POINTS: IndexPoint[] = [
  point({
    date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null,
    constituent_count: 0, eligible_print_count: 231,
    movers_up: null, movers_down: null, movers_flat: null, capped_count: null,
  }),
  point({ date: "2026-09-04", value: "1000.8409", prior_point_date: "2026-09-03",
    constituent_count: 231, eligible_print_count: 281, movers_up: 1, movers_flat: 230 }),
  point({ date: "2026-09-05", value: "1000.9577", prior_point_date: "2026-09-04",
    constituent_count: 281, eligible_print_count: 296, movers_up: 1, movers_flat: 280 }),
  point({ date: "2026-09-06", value: "1000.9577", prior_point_date: "2026-09-05",
    constituent_count: 296, eligible_print_count: 297 }),
  point({ date: "2026-09-07", value: "1000.1065", prior_point_date: "2026-09-06",
    constituent_count: 296, eligible_print_count: 305,
    movers_up: 1, movers_down: 3, movers_flat: 292, capped_count: 2 }),
];

function series(partial: Partial<IndexSeries> = {}): IndexSeries {
  return {
    scope_kind: "overall",
    scope_key: "",
    methodology_version: 1,
    index_version: 3,
    source_semantics_version: 2,
    requested_window: "all",
    window_start: null,
    available_from: "2026-09-03",
    available_to: "2026-09-07",
    covers_requested_window: true,
    points: POINTS,
    starting_value: "1000.0000",
    current_value: "1000.1065",
    low_value: "1000.0000",
    high_value: "1000.9577",
    change: {
      absolute: "0.1065",
      pct: "0.010650",
      from_date: "2026-09-03",
      to_date: "2026-09-07",
      spans_break: false,
    },
    change_unavailable_reason: null,
    windows: WINDOWS,
    default_window: "all",
    breaks: [],
    ...partial,
  };
}

function windowRow(
  token: string,
  available: boolean,
  covered_days = 5,
  required_days: number | null = null,
): IndexWindowRow {
  return { token, available, covered_days, required_days };
}

/** Staging's real map on 2026-09-07: five days of archive, so the server
 * reports every duration window as unspanned and only `all` as available. */
const WINDOWS: IndexWindowRow[] = [
  windowRow("2w", false, 5, 14),
  windowRow("1m", false, 5, 30),
  windowRow("3m", false, 5, 90),
  windowRow("6m", false, 5, 180),
  windowRow("1y", false, 5, 365),
  windowRow("2y", false, 5, 730),
  windowRow("all", true, 5, null),
];


function renderHero(data: IndexSeries | null = series(), status: "ready" | "error" | "loading" = "ready") {
  const onWindowChange = vi.fn();
  render(<CardPirateIndexHero series={data} status={status} refreshing={false} window="all" onWindowChange={onWindowChange} />);
  return onWindowChange;
}
it("retains the server-authored CPI level and distinct change for other surfaces", () => {
  renderHero();
  expect(screen.getByTestId("index-level")).toHaveTextContent("1,000.11");
  expect(screen.getByRole("heading", { name: "Card Pirate Index" })).toBeInTheDocument();
});
it("uses the supplied window vocabulary and blocks unavailable windows", () => {
  const change = renderHero();
  fireEvent.click(screen.getByRole("button", { name: /^2W/ }));
  expect(change).not.toHaveBeenCalled();
});
it("keeps a missing movement distinct from a flat one", () => {
  renderHero(series({ change: null, change_unavailable_reason: "insufficient_history" }));
  expect(screen.queryByTestId("index-change")).not.toBeInTheDocument();
  expect(screen.getByTestId("index-change-unavailable")).toHaveTextContent("Change not available across this period");
  expect(screen.getByTestId("index-level")).toBeInTheDocument();
});
it("keeps its chart and watermark available independently of the new Market page", () => {
  renderHero();
  expect(screen.getByTestId("index-chart")).toBeInTheDocument();
  expect(screen.getByTestId("index-watermark")).toBeInTheDocument();
});
it("renders a local CPI error", () => {
  renderHero(null, "error");
  expect(screen.getByText(/index could not be loaded/)).toBeInTheDocument();
});
