import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import fixtures from "@/lib/__fixtures__/marketValueReleases.json";
import type { MarketValue } from "@/lib/marketValue";
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  LineChart: ({ children, data }: { children: ReactNode; data: unknown }) => <div data-testid="comparison-data" data-rows={JSON.stringify(data)}>{children}</div>,
  Line: ({ name, dataKey, connectNulls }: { name: string; dataKey: string; connectNulls: boolean }) => <div data-testid="comparison-line" data-key={dataKey} data-connect={String(connectNulls)}>{name}</div>,
  ReferenceLine: ({ y }: { y: number }) => <div data-testid="baseline">{y}</div>,
  CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}));
import { MarketValueComparisonChart, MarketValueComparisonTooltip } from "./MarketValueComparisonChart";
const lines = (Object.values(fixtures.series).slice(0, 2) as MarketValue[]).map((data, slot) => ({ id: data.release_product_id!, code: data.release_code!, label: "English name", slot, data }));
it("plots one line per selected release with a zero baseline and server performance", () => {
  render(<MarketValueComparisonChart lines={lines} />);
  const rows = JSON.parse(screen.getByTestId("comparison-data").getAttribute("data-rows")!);
  expect(rows.at(-1).values[lines[0].id]).toBe(Number(lines[0].data.series.at(-1)!.performance_pct));
  expect(screen.getAllByTestId("comparison-line").map((line) => line.textContent)).toEqual(lines.map((line) => line.code));
  expect(screen.getAllByTestId("comparison-line")[0]).toHaveAttribute("data-connect", "false");
  expect(screen.getByTestId("baseline")).toHaveTextContent("0");
});
it("shows compact dated tooltip rows, signs and release codes", () => {
  render(<MarketValueComparisonTooltip active lines={lines} payload={[{ payload: { date: "2026-09-26", timestamp: 0, values: { [lines[0].id]: 4.2, [lines[1].id]: -3.1 } } }]} />);
  expect(screen.getByText("Sep 26, 2026")).toBeInTheDocument();
  expect(screen.getByText("+4.20%")).toBeInTheDocument();
  expect(screen.getByText("−3.10%")).toBeInTheDocument();
  expect(screen.getByText(lines[0].code)).toHaveAttribute("style");
  expect(document.body.textContent).not.toMatch(/factor|segment|methodology/i);
});
it("withholds incompatible periods instead of inventing a shared chart", () => {
  const incompatible = structuredClone(lines);
  incompatible[1].data.series.pop();
  render(<MarketValueComparisonChart lines={incompatible} />);
  expect(screen.getByText("Comparison unavailable")).toBeInTheDocument();
  expect(screen.queryByTestId("comparison-line")).not.toBeInTheDocument();
});
