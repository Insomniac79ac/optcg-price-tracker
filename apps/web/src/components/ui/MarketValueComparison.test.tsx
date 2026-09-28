import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import fixtures from "@/lib/__fixtures__/marketValueReleases.json";
import type { MarketValue } from "@/lib/marketValue";
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiGet }));
vi.mock("./MarketValueComparisonChart", async () => ({
  ...await vi.importActual("./MarketValueComparisonChart"),
  MarketValueComparisonChart: ({ lines }: { lines: { id: number; data: MarketValue }[] }) => <div data-testid="comparison-chart">{lines.map((line) => <span key={line.id}>{line.data.release_code}: {line.data.movement.pct}</span>)}</div>,
}));
import { MarketValueComparison } from "./MarketValueComparison";
const releases = fixtures.releases.items;
const series = fixtures.series as unknown as Record<string, MarketValue>;
const eligible = releases.filter((r) => r.seven_day.available);
const id = (code: string) => releases.find((release) => release.release_code === code)!.release_product_id;
const props = { releases, failed: false, loading: false };
function open() { fireEvent.click(screen.getByRole("button", { name: /^Compare releases/ })); }
function select(code: string) { fireEvent.click(screen.getByRole("checkbox", { name: new RegExp(`^${code} —`) })); }
function deferred<T>() { let resolve!: (v: T) => void; let reject!: (e: Error) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { resolve, reject, promise }; }
async function settled() { await waitFor(() => expect(screen.getByTestId("comparison-settled")).toHaveAttribute("aria-busy", "false")); }
beforeEach(() => { apiGet.mockReset().mockImplementation((_, options) => Promise.resolve(series[options.params.release_product_id])); });

it("starts empty, offers only 7D, and never fetches all release series", () => {
  render(<MarketValueComparison {...props} />);
  expect(screen.getByText("Choose up to 4 releases to compare their 7D price movement.")).toBeInTheDocument();
  expect(screen.getByText("7D performance")).toBeInTheDocument();
  expect(screen.queryByTestId("comparison-chart")).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(apiGet).not.toHaveBeenCalled();
});
it("uses only server eligibility, English names, and searchable disabled annotations", async () => {
  const lowCoverage = releases.map((release) => release.release_code === "OP-01" ? { ...release, tracked_value: { ...release.tracked_value, priced_print_count: 1, physical_coverage_pct: "0.1" } } : release);
  render(<MarketValueComparison {...props} releases={lowCoverage} />);
  open();
  const ineligible = screen.getByRole("checkbox", { name: "OP-17 — The World's Strongest Warriors" });
  expect(ineligible).toBeDisabled();
  expect(ineligible).toHaveAccessibleDescription("Price coverage in progress");
  expect(screen.getByRole("checkbox", { name: "OP-01 — Romance Dawn" })).toBeEnabled();
  expect(document.body.textContent).not.toContain("原題");
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Romance Dawn" } });
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  select("OP-01");
  await settled();
  expect(apiGet.mock.calls).toEqual([["/analytics/market-value", { params: { release_product_id: 181, window: "7d" } }]]);
});
it("enforces four selections, preserves chosen order, and removes without refetching", async () => {
  render(<MarketValueComparison {...props} />);
  open();
  for (const release of eligible.slice(0, 4)) select(release.release_code);
  await settled();
  expect(apiGet).toHaveBeenCalledTimes(4);
  expect(screen.getByText("4 of 4 selected. Remove one to add another.")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: new RegExp(`^${eligible[4].release_code} —`) })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  const legend = within(screen.getByRole("list", { name: "Comparison legend" }));
  expect(legend.getAllByRole("listitem").map((item) => item.textContent)).toEqual(eligible.slice(0, 4).map((r) => `${r.release_code}×`));
  fireEvent.click(screen.getByRole("button", { name: `Remove ${eligible[1].release_code}` }));
  expect(apiGet).toHaveBeenCalledTimes(4);
  expect(legend.getAllByRole("listitem")).toHaveLength(3);
  open(); select(eligible[4].release_code); await settled();
  expect(apiGet).toHaveBeenCalledTimes(5);
});
it("keeps existing plots during an addition and provides the hero-strength watermark", async () => {
  render(<MarketValueComparison {...props} />); open(); select("OP-01"); await settled();
  const slow = deferred<MarketValue>(); apiGet.mockReturnValueOnce(slow.promise);
  select("OP-04");
  expect(screen.getByTestId("comparison-settled")).toHaveAttribute("aria-busy", "true");
  expect(screen.getByTestId("comparison-chart")).toHaveTextContent("OP-01: 4.20");
  expect(screen.getByTestId("comparison-watermark")).toHaveTextContent("CARDPIRATE ATLAScardpirateatlas.com");
  await act(async () => slow.resolve(series[id("OP-04")]));
  expect(screen.getByTestId("comparison-chart")).toHaveTextContent("OP-04: -3.10");
});
it("keeps successful lines when one fails, with independent retry and removal", async () => {
  apiGet.mockImplementation((_, options) => options.params.release_product_id === id("OP-04") ? Promise.reject(new Error("failed")) : Promise.resolve(series[options.params.release_product_id]));
  render(<MarketValueComparison {...props} />); open(); select("OP-01"); select("OP-04"); await settled();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.getByTestId("comparison-chart")).toHaveTextContent("OP-01");
  expect(screen.getByText(/OP-04 could not be loaded/)).toBeInTheDocument();
  apiGet.mockClear().mockResolvedValue(series[id("OP-04")]);
  fireEvent.click(screen.getByRole("button", { name: "Retry OP-04" })); await settled();
  expect(apiGet).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId("comparison-chart")).toHaveTextContent("OP-04");
  fireEvent.click(screen.getByRole("button", { name: "Remove OP-04" }));
  expect(screen.getByTestId("comparison-chart")).not.toHaveTextContent("OP-04");
});
it.each(["success", "failure"])("ignores late %s after removing and re-adding the same release", async (result) => {
  const slow = deferred<MarketValue>();
  apiGet.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ ...series[181], movement: { ...series[181].movement, pct: "9.99" } });
  render(<MarketValueComparison {...props} />); open(); select("OP-01"); select("OP-01"); select("OP-01"); await settled();
  await act(async () => result === "success" ? slow.resolve(series[181]) : slow.reject(new Error("late")));
  expect(screen.getByTestId("comparison-chart")).toHaveTextContent("9.99");
  expect(screen.queryByRole("button", { name: "Retry OP-01" })).not.toBeInTheDocument();
  expect(apiGet).toHaveBeenCalledTimes(2);
});
it("does not re-request series when the shared release list rerenders", async () => {
  const view = render(<MarketValueComparison {...props} />); open(); select("OP-01"); await settled();
  view.rerender(<MarketValueComparison {...props} releases={[...releases]} />);
  expect(apiGet).toHaveBeenCalledTimes(1);
});
