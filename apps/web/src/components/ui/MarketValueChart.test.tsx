import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AreaChart: ({ children, data }: { children: ReactNode; data: unknown }) => <div data-testid="chart-data" data-rows={JSON.stringify(data)}>{children}</div>,
  Area: ({ connectNulls }: { connectNulls: boolean }) => <div data-testid="line" data-connect-nulls={String(connectNulls)} />,
  CartesianGrid: () => null, ReferenceLine: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}));
import { MarketValueChart, MarketValueChartTooltip } from "./MarketValueChart";
import { MarketValueHero, type MarketValueHeroProps } from "./MarketValueHero";
import fixtures from "@/lib/__fixtures__/marketValue.json";
import type { MarketValue } from "@/lib/marketValue";

it("plots the supplied server performance and does not join nulls", () => {
  const series = fixtures.overall.series.map((point, index) => ({ ...point, performance_pct: index === 2 ? null : point.performance_pct }));
  render(<MarketValueChart series={series} mode="performance" />);
  const rows = JSON.parse(screen.getByTestId("chart-data").getAttribute("data-rows")!);
  expect(rows.map((row: { value: number | null }) => row.value)).toEqual([0, -0.058292, null, -2.297329, -2.781736, -3.169077, -2.750053, -3.943982]);
  expect(screen.getByTestId("line")).toHaveAttribute("data-connect-nulls", "false");
});
it("plots literal JPY values in Tracked value mode", () => {
  render(<MarketValueChart series={fixtures.overall.series} mode="value" />);
  const rows = JSON.parse(screen.getByTestId("chart-data").getAttribute("data-rows")!);
  expect(rows.map((row: { value: number | null }) => row.value)).toEqual(fixtures.overall.series.map((p) => p.tracked_value_jpy));
});
it("does not draw an empty or fully unavailable series as a flat line", () => {
  render(<MarketValueChart series={fixtures.sparse.series} mode="performance" />);
  expect(screen.queryByTestId("line")).not.toBeInTheDocument();
});
it("keeps compact tooltip contents specific to the mode", () => {
  const row = { date: "2026-09-26", timestamp: 0, value: -3.943982, priced: 639, physical: 4316 };
  const view = render(<MarketValueChartTooltip active payload={[{ payload: row }]} mode="performance" />);
  expect(screen.getByText("Sep 26, 2026")).toBeInTheDocument();
  expect(screen.getByText("−3.94%")).toBeInTheDocument();
  expect(screen.queryByText(/printings priced/)).not.toBeInTheDocument();
  view.rerender(<MarketValueChartTooltip active payload={[{ payload: { ...row, value: 262279 } }]} mode="value" />);
  expect(screen.getByText("¥262,279")).toBeInTheDocument();
  expect(screen.getByText("639 / 4,316 card variants priced")).toBeInTheDocument();
});
it("never gives a missing point a tooltip value", () => {
  const { container } = render(<MarketValueChartTooltip active payload={[{ payload: { date: "2026-09-26", timestamp: 0, value: null, priced: 0, physical: 0 } }]} mode="value" />);
  expect(container).toHaveTextContent("Market data unavailable");
  expect(container).not.toHaveTextContent("¥0");
});
it("keeps readable branding inside the hero for either chart mode", () => {
  const props: MarketValueHeroProps = { data: fixtures.overall as MarketValue, busy: false, error: null, releases: [], releasesFailed: false, releaseProductId: null, window: "7d", mode: "performance", onScopeChange: vi.fn(), onWindowChange: vi.fn(), onModeChange: vi.fn(), onRetry: vi.fn() };
  const view = render(<MarketValueHero {...props} />);
  const brand = screen.getByTestId("market-watermark");
  expect(screen.getByTestId("market-value-hero")).toContainElement(brand);
  expect(brand).toHaveTextContent("CARD PIRATEJapanese card prices · JPY");
  view.rerender(<MarketValueHero {...props} mode="value" />);
  expect(screen.getByTestId("market-watermark")).toHaveTextContent("CARD PIRATE");
});

it.each([null, 1])("renders persisted JPY history independently of an unavailable comparison (scope %s)", (releaseId) => {
  const data = { ...fixtures.overall, scope_kind: releaseId ? "release" : "overall", release_product_id: releaseId,
    movement: { ...fixtures.overall.movement, available: false, pct: null, reason: "insufficient_window_continuity" },
    series: [
      { ...fixtures.overall.series[0], date: "2026-09-26", tracked_value_jpy: 100 },
      { ...fixtures.overall.series[1], date: "2026-09-29", tracked_value_jpy: 200, performance_pct: null },
    ],
  } as MarketValue;
  render(<MarketValueHero data={data} busy={false} error={null} releases={[]} releasesFailed={false} releaseProductId={releaseId}
    window="7d" mode="value" onScopeChange={vi.fn()} onWindowChange={vi.fn()} onModeChange={vi.fn()} onRetry={vi.fn()} />);
  const rows = JSON.parse(screen.getByTestId("chart-data").getAttribute("data-rows")!);
  expect(rows.map((r: { value: number | null }) => r.value)).toEqual([100, null, null, 200]);
  expect(screen.getByTestId("market-movement-unavailable")).toHaveTextContent("7D Unavailable");
  expect(screen.queryByTestId("market-movement")).not.toBeInTheDocument();
  expect(screen.getByTestId("line")).toHaveAttribute("data-connect-nulls", "false");
});
it("renders one real point, and no line for an empty or unpriced history", () => {
  const view = render(<MarketValueChart series={fixtures.overall.series.slice(0, 1)} mode="value" />);
  expect(screen.getByTestId("line")).toBeInTheDocument();
  view.rerender(<MarketValueChart series={[]} mode="value" />);
  expect(screen.queryByTestId("line")).not.toBeInTheDocument();
  view.rerender(<MarketValueChart series={[{ ...fixtures.overall.series[0], tracked_value_jpy: null }]} mode="value" />);
  expect(screen.queryByTestId("line")).not.toBeInTheDocument();
});
