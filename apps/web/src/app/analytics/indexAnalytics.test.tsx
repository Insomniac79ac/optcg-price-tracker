/** Retained CPI composition/breadth components, no longer mounted by /analytics. */
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { IndexCompositionPanel } from "@/components/ui/IndexCompositionPanel";
import { MarketBreadthPanel } from "@/components/ui/MarketBreadthPanel";
import type { IndexComposition, IndexPoint } from "@/lib/cardPirateIndex";
function point(partial: Partial<IndexPoint> = {}): IndexPoint {
  return {
    date: "2026-09-07",
    value: "1000.1065",
    is_base: false,
    prior_point_date: "2026-09-06",
    step_days: 1,
    chain_link_log_return: "-0.000850790688",
    constituent_count: 296,
    eligible_print_count: 305,
    movers_up: 1,
    movers_down: 3,
    movers_flat: 292,
    capped_count: 2,
    ...partial,
  };
}

function composition(partial: Partial<IndexComposition> = {}): IndexComposition {
  return {
    as_of: "2026-09-07",
    constituent_count: 296,
    rarity: [
      { key: "C", label: "C", count: 134, pct: 45.27 },
      { key: "R", label: "R", count: 70, pct: 23.65 },
      { key: "UC", label: "UC", count: 69, pct: 23.31 },
      { key: "SR", label: "SR", count: 10, pct: 3.38 },
      { key: "L", label: "L", count: 7, pct: 2.36 },
      { key: "SP CARD", label: "SP CARD", count: 6, pct: 2.03 },
    ],
    ...partial,
  };
}


it("renders the published composition count and server percentages", () => {
  render(<IndexCompositionPanel composition={composition()} status="ready" />);
  expect(screen.getByTestId("composition-count")).toHaveTextContent("296");
  expect(screen.getByTestId("composition-legend")).toHaveTextContent("45.27%");
});
it("keeps unavailable composition local", () => {
  render(<IndexCompositionPanel composition={null} status="error" />);
  expect(screen.getByTestId("composition-unavailable")).toBeInTheDocument();
});
it("renders the supplied breadth counts without deriving movement from prices", () => {
  render(<MarketBreadthPanel point={point()} />);
  expect(screen.getByTestId("breadth-up")).toHaveTextContent("1");
  expect(screen.getByTestId("breadth-down")).toHaveTextContent("3");
  expect(screen.getByTestId("breadth-flat")).toHaveTextContent("292");
});
it("keeps missing breadth distinct from zero", () => {
  render(<MarketBreadthPanel point={null} />);
  expect(screen.getByTestId("breadth-unavailable")).toBeInTheDocument();
});
