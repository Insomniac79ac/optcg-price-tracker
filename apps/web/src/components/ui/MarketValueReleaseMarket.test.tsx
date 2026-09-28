import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import fixtures from "@/lib/__fixtures__/marketValueReleases.json";
import { MarketValueReleaseMarket } from "./MarketValueReleaseMarket";
const releases = fixtures.releases.items;
const props = { releases, loading: false, failed: false, onScopeChange: vi.fn() };
const rows = () => within(screen.getByRole("list", { name: "Release markets" })).getAllByRole("listitem");
function search(value: string) { fireEvent.change(screen.getByRole("searchbox", { name: "Search releases" }), { target: { value } }); }

it("shows the first twelve in server order and expands the already-loaded census", () => {
  // Order intentionally includes mixed products and IDs; do not sort by either.
  const reordered = [releases[17], releases[16], ...releases.filter((_, i) => i !== 17 && i !== 16)];
  render(<MarketValueReleaseMarket {...props} releases={reordered} />);
  expect(rows()).toHaveLength(12);
  expect(rows().map((row) => row.querySelector("strong")?.textContent)).toEqual(reordered.slice(0, 12).map((r) => r.release_code));
  fireEvent.click(screen.getByRole("button", { name: /Show more/ }));
  expect(rows()).toHaveLength(24);
  expect(rows()[23]).toHaveTextContent(reordered[23].release_code);
});
it("reports partial JPY, coverage counts and percentages with honest unavailable movement", () => {
  render(<MarketValueReleaseMarket {...props} />);
  expect(rows()[0]).toHaveTextContent("OP-17The World's Strongest Warriors");
  expect(rows()[0]).toHaveTextContent("¥14,780");
  expect(rows()[0]).toHaveTextContent("20 / 169 priced");
  expect(rows()[0]).toHaveTextContent("11.83%");
  expect(rows()[0]).toHaveTextContent("7D —Coverage in progress");
  expect(rows()[0]).toHaveTextContent("30D —Not enough history");
  expect(rows()[0]).not.toHaveTextContent("0.00%");
  expect(screen.getByText(/Prices through/)).toHaveTextContent("Sep 26, 2026");
  expect(document.body.textContent).not.toMatch(/insufficient_|原題|Market cap|Total market value|winner|best performer/i);
});
it("shows available movement and explicitly qualifies sparse tracked value", () => {
  render(<MarketValueReleaseMarket {...props} />);
  search("OP-01"); expect(rows()[0]).toHaveTextContent("7D +4.20%");
  search("OP-05"); expect(rows()[0]).toHaveTextContent("¥480Tracked so far");
  expect(rows()[0]).toHaveTextContent("4 / 154 priced");
});
it("searches the full census by code and English name without changing order", () => {
  render(<MarketValueReleaseMarket {...props} />);
  search("st-01"); expect(rows()).toHaveLength(1); expect(rows()[0]).toHaveTextContent("Straw Hat Crew");
  search("heroines"); expect(rows()).toHaveLength(1); expect(rows()[0]).toHaveTextContent("EB-03");
  search("not a release"); expect(screen.getByText("No releases match your search.")).toBeInTheDocument();
  search(""); expect(rows()).toHaveLength(12);
});
it("selects the authoritative scope and includes readable mobile labels", () => {
  const change = vi.fn();
  render(<MarketValueReleaseMarket {...props} onScopeChange={change} />);
  fireEvent.click(screen.getByRole("button", { name: "View OP-17 — The World's Strongest Warriors Market" }));
  expect(change).toHaveBeenCalledExactlyOnceWith(198);
  expect(rows()[0]).toHaveTextContent("Tracked ¥14,780");
  expect(rows()[0]).toHaveTextContent("7D —");
  expect(rows()[0]).toHaveTextContent("30D —");
  expect(rows()[0]).toHaveTextContent("Tap for Market view →");
});
it("keeps unpriced releases null and a real flat 7D distinct from unavailable", () => {
  render(<MarketValueReleaseMarket {...props} releases={[{ ...releases[0], tracked_value: { ...releases[0].tracked_value, value_jpy: null, physical_coverage_pct: null }, seven_day: { available: true, pct: "0", reason: "publishable" } }]} />);
  expect(rows()[0]).toHaveTextContent("Not yet priced");
  expect(rows()[0]).not.toHaveTextContent("¥0");
  expect(rows()[0]).toHaveTextContent("7D 0.00%");
  expect(rows()[0]).toHaveTextContent("30D —Not enough history");
});
it("keeps shared-list loading, failure and empty states local", () => {
  const view = render(<MarketValueReleaseMarket {...props} loading releases={[]} />);
  expect(screen.getByText("Loading release markets…")).toBeInTheDocument();
  view.rerender(<MarketValueReleaseMarket {...props} failed releases={[]} />);
  expect(screen.getByText("Release markets could not be loaded.")).toBeInTheDocument();
  view.rerender(<MarketValueReleaseMarket {...props} releases={[]} />);
  expect(screen.getByText("No release markets yet.")).toBeInTheDocument();
});
