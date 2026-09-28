import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixtures from "@/lib/__fixtures__/marketValueRankings.json";
import type { MarketValueMostValuable, MarketValueMovers } from "@/lib/marketValue";
import { MarketValueMostValuableSection, MarketValueMoversSection } from "./MarketValueDiscovery";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiGet }));
const BASE = "/analytics/market-value";
const gainers = fixtures.gainers as MarketValueMovers;
const valuable = fixtures.valuable as MarketValueMostValuable;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
async function settled(id = "movers-settled") {
  await waitFor(() => expect(screen.getByTestId(id)).toHaveAttribute("aria-busy", "false"));
}
beforeEach(() => {
  apiGet.mockReset().mockImplementation((path, options) => Promise.resolve(path.endsWith("/movers") ? fixtures[(options.params.order ?? "gainers") as "gainers"] : valuable));
});

describe("daily Market Value movers", () => {
  it("requests gainers, then each selected server cohort, with explicit directions and exact print links", async () => {
    render(<MarketValueMoversSection releaseProductId={null} />);
    await settled();
    expect(apiGet).toHaveBeenLastCalledWith(`${BASE}/movers`, { params: { release_product_id: null, order: "gainers", limit: 5 } });
    expect(screen.getAllByTestId("mover-primary")[0]).toHaveTextContent("+18.40%↗ Up");
    const first = screen.getAllByRole("link")[0];
    expect(first).toHaveAttribute("href", "/prints/8101");
    expect(first).toHaveTextContent("OP01-016OP-01");
    expect(first).toHaveTextContent("¥2,500 → ¥2,960");
    expect(first).toHaveTextContent("Basket change +¥460");
    expect(screen.queryByText(/percentage points/)).not.toBeInTheDocument();
    expect(screen.getByText(/Movement:/)).toHaveTextContent("Movement: Sep 25 → Sep 26");
    fireEvent.click(screen.getByRole("button", { name: "Losers" }));
    await settled();
    expect(apiGet).toHaveBeenLastCalledWith(`${BASE}/movers`, { params: { release_product_id: null, order: "losers", limit: 5 } });
    expect(screen.getAllByTestId("mover-primary")[0]).toHaveTextContent("−20.00%↘ Down");
    expect(screen.getAllByRole("link")[0]).toHaveTextContent("Basket change −¥1,000");
    fireEvent.click(screen.getByRole("button", { name: "Market impact" }));
    await settled();
    expect(apiGet).toHaveBeenLastCalledWith(`${BASE}/movers`, { params: { release_product_id: null, order: "impact", limit: 5 } });
    expect(screen.getAllByTestId("mover-primary")[0]).toHaveTextContent("−¥3,200↘ Down");
    expect(screen.getAllByRole("link")[0]).toHaveTextContent("Impact −1.21 percentage points");
    expect(screen.getAllByRole("link")[0]).toHaveTextContent("Card price −14.81%");
    expect(screen.getByText("Largest contributors to the latest basket move.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/CPI|contribution_log_return|approx_index_points|7D movers|30D movers/);
  });

  it("propagates only the authoritative release ID and selected order", async () => {
    render(<MarketValueMoversSection releaseProductId={186} />);
    await settled();
    fireEvent.click(screen.getByRole("button", { name: "Losers" }));
    await settled();
    expect(apiGet.mock.calls.map(([, options]) => options.params)).toEqual([
      { release_product_id: 186, order: "gainers", limit: 5 },
      { release_product_id: 186, order: "losers", limit: 5 },
    ]);
  });

  it("keeps unavailable coverage distinct from a valid flat step", async () => {
    apiGet.mockResolvedValueOnce(fixtures.unavailable).mockResolvedValueOnce(fixtures.flat);
    const view = render(<MarketValueMoversSection releaseProductId={186} />);
    await settled();
    expect(screen.getByText("No published price movement yet")).toBeInTheDocument();
    expect(screen.getByText("Price coverage is still being built for this release.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("no_published_daily_step");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    view.rerender(<MarketValueMoversSection releaseProductId={181} />);
    await settled();
    expect(screen.getByText("No cards moved in the latest published step.")).toBeInTheDocument();
    expect(screen.queryByText(/coverage/i)).not.toBeInTheDocument();
  });

  it("labels an older published step without claiming latest prices", async () => {
    apiGet.mockResolvedValue({ ...gainers, step_date: "2026-09-24", prior_date: "2026-09-23" });
    render(<MarketValueMoversSection releaseProductId={null} />);
    await settled();
    expect(screen.getByText(/Latest published movement:/)).toHaveTextContent("Latest published movement: Sep 24");
    expect(document.body.textContent).not.toMatch(/latest prices/i);
  });

  it("retains prior cards AND their metric mode, then ignores a slower abandoned tab", async () => {
    render(<MarketValueMoversSection releaseProductId={null} />);
    await settled();
    const slow = deferred<MarketValueMovers>();
    apiGet.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(fixtures.losers);
    fireEvent.click(screen.getByRole("button", { name: "Market impact" }));
    expect(screen.getByTestId("movers-settled")).toHaveAttribute("aria-busy", "true");
    expect(screen.getAllByTestId("mover-primary")[0]).toHaveTextContent("+18.40%");
    expect(screen.getByRole("status")).toHaveTextContent("Showing previous gainers for All One Piece");
    fireEvent.click(screen.getByRole("button", { name: "Losers" }));
    await settled();
    await act(async () => slow.resolve(fixtures.impact as MarketValueMovers));
    expect(screen.getAllByTestId("mover-primary")[0]).toHaveTextContent("−20.00%");
    expect(screen.getByRole("button", { name: "Losers" })).toHaveAttribute("aria-pressed", "true");
  });

  it.each(["success", "failure"])("ignores a late scope %s", async (result) => {
    const slow = deferred<MarketValueMovers>();
    apiGet.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(fixtures.unavailable);
    const view = render(<MarketValueMoversSection releaseProductId={181} />);
    view.rerender(<MarketValueMoversSection releaseProductId={186} />);
    await settled();
    await act(async () => result === "success" ? slow.resolve(gainers) : slow.reject(new Error("old")));
    expect(screen.getByText("No published price movement yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("uses the image resolver, full contain artwork and existing broken-image fallback", async () => {
    render(<MarketValueMoversSection releaseProductId={null} />);
    await settled();
    const art = screen.getAllByRole("img")[0];
    expect(art.getAttribute("src")).toMatch(/^\/api\/card-image\?u=/);
    expect(art).toHaveClass("object-contain", "p-1.5");
    fireEvent.error(art);
    const first = within(screen.getAllByRole("link")[0]);
    expect(first.queryByRole("img")).not.toBeInTheDocument();
    expect(first.getAllByText("OP01-016")).toHaveLength(2);
  });
});

describe("snapshot-aligned most valuable prints", () => {
  it("requests six, preserves exact-print siblings and server order, and shows shared valuation date", async () => {
    // Deliberately non-price order to prove the client never sorts the payload.
    const items = [valuable.items[1], valuable.items[0], ...valuable.items.slice(2)];
    apiGet.mockResolvedValue({ ...valuable, items });
    render(<MarketValueMostValuableSection releaseProductId={null} releaseCode={null} />);
    await settled("valuable-settled");
    expect(apiGet).toHaveBeenCalledWith(`${BASE}/most-valuable`, { params: { release_product_id: null, limit: 6 } });
    const links = within(screen.getByRole("list")).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual(items.map((item) => `/prints/${item.card_print_id}`));
    expect(links[0]).toHaveTextContent("Monkey.D.LuffyOP05-119OP-05¥72,000Tracked value");
    expect(links[1]).toHaveTextContent("Monkey.D.LuffyOP05-119OP-05¥98,000Tracked value");
    expect(screen.getAllByRole("img")).toHaveLength(6);
    expect(screen.getByText(/Prices through/)).toHaveTextContent("Prices through Sep 26");
    expect(screen.getByRole("link", { name: "Browse all cards →" })).toHaveAttribute("href", "/cards");
    expect(document.body.textContent).not.toMatch(/market cap|live prices/i);
  });

  it("uses release code from the response even if the release list is unavailable", async () => {
    apiGet.mockResolvedValue({ ...valuable, scope_kind: "release", release_product_id: 186, release_code: "OP-05" });
    render(<MarketValueMostValuableSection releaseProductId={186} releaseCode={null} />);
    await settled("valuable-settled");
    expect(screen.getByRole("heading", { name: "Most valuable in OP-05" })).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith(`${BASE}/most-valuable`, { params: { release_product_id: 186, limit: 6 } });
    expect(screen.getByRole("link", { name: "Browse all cards →" })).toHaveAttribute("href", "/cards?release_product_id=186");
  });

  it("shows a clean unpriced state without a zero value or card skeletons", async () => {
    apiGet.mockResolvedValue({ ...valuable, total_eligible: 0, items: [] });
    render(<MarketValueMostValuableSection releaseProductId={null} releaseCode={null} />);
    await settled("valuable-settled");
    expect(screen.getByText("No priced cards yet for this scope.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("¥0");
  });

  it.each(["success", "failure"])("keeps settled prices during refresh and ignores a late scope %s", async (result) => {
    const view = render(<MarketValueMostValuableSection releaseProductId={null} releaseCode={null} />);
    await settled("valuable-settled");
    const slow = deferred<MarketValueMostValuable>();
    apiGet.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ ...valuable, scope_kind: "release", release_product_id: 181, release_code: "OP-01", as_of: "2026-09-24", items: [valuable.items[4]] });
    view.rerender(<MarketValueMostValuableSection releaseProductId={186} releaseCode="OP-05" />);
    expect(screen.getByTestId("valuable-settled")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(/Prices through/)).toHaveTextContent("Sep 26");
    expect(within(screen.getByRole("list")).getAllByRole("link")).toHaveLength(6);
    expect(screen.getByRole("status")).toHaveTextContent("Showing previous prices for All One Piece");
    view.rerender(<MarketValueMostValuableSection releaseProductId={181} releaseCode="OP-01" />);
    await settled("valuable-settled");
    await act(async () => result === "success" ? slow.resolve(valuable) : slow.reject(new Error("old")));
    expect(screen.getByRole("heading", { name: "Most valuable in OP-01" })).toBeInTheDocument();
    expect(screen.getByText(/Prices through/)).toHaveTextContent("Sep 24");
    expect(within(screen.getByRole("list")).getAllByRole("link")).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
