import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <nav>Atlas navigation</nav> }));
vi.mock("next/navigation", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    useSearchParams: () => {
      const [, refresh] = React.useReducer((n: number) => n + 1, 0);
      React.useEffect(() => {
        window.addEventListener("popstate", refresh);
        return () => window.removeEventListener("popstate", refresh);
      }, []);
      return new URLSearchParams(window.location.search);
    },
  };
});
// The real chart's geometry/tooltips have separate tests and browser coverage.
vi.mock("@/components/ui/MarketValueChart", () => ({
  MarketValueChart: ({ series, mode }: { series: unknown; mode: string }) => <div data-testid="market-value-chart" data-mode={mode}>{JSON.stringify(series)}</div>,
}));
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api", async () => ({ ...await vi.importActual("@/lib/api"), apiGet }));

import MarketPage from "./MarketClient";
import { ApiError } from "@/lib/api";
import fixtures from "@/lib/__fixtures__/marketValue.json";
import rankings from "@/lib/__fixtures__/marketValueRankings.json";

const BASE = "/analytics/market-value";
function navigate(url: string) {
  act(() => {
    window.history.pushState(null, "", url);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function stub(path: string, options?: { params?: { release_product_id?: number; window?: string; order?: "gainers" | "losers" | "impact" } }) {
  if (path === `${BASE}/releases`) return Promise.resolve(fixtures.releases);
  if (path === `${BASE}/movers`) return Promise.resolve(rankings[options?.params?.order ?? "gainers"]);
  if (path === `${BASE}/most-valuable`) return Promise.resolve(rankings.valuable);
  if (path !== BASE) return Promise.reject(new Error(`Forbidden B1 request: ${path}`));
  if (options?.params?.release_product_id === 186) return Promise.resolve(fixtures.sparse);
  if (options?.params?.release_product_id === 181) return Promise.resolve(fixtures.eligible);
  if (options?.params?.window === "30d") return Promise.resolve(fixtures.thirtyDay);
  if (options?.params?.window === "all") return Promise.resolve(fixtures.all);
  return Promise.resolve(fixtures.overall);
}
async function ready() {
  render(<MarketPage />);
  await waitFor(() => expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "false"));
}
beforeEach(() => {
  window.history.replaceState(null, "", "/analytics");
  apiGet.mockReset().mockImplementation(stub);
});

describe("Market Value hero", () => {
  it("keeps the selected window in the shareable URL and follows history navigation", async () => {
    navigate("/analytics?window=30d");
    await ready();
    expect(screen.getByTestId("market-coverage-state")).toHaveTextContent("this 30D window");
    fireEvent.click(within(screen.getByRole("group", { name: "Market window" })).getByRole("button", { name: "ALL" }));
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("ALL"));
    expect(window.location.search).toBe("?window=all");
    navigate("/analytics");
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("7D"));
  });
  it("leads with Overall 7D movement, and attaches partial coverage to the secondary JPY value", async () => {
    await ready();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("How is the One Piece market doing?");
    expect(screen.getByTestId("market-movement")).toHaveTextContent("−3.94%7D");
    const tracked = screen.getByTestId("market-tracked-value");
    expect(tracked).toHaveTextContent("¥262,279");
    expect(tracked).toHaveTextContent("639 of 4,316 card variants priced");
    expect(tracked).toHaveTextContent("14.8% coverage");
    expect(screen.getByText(/Published/)).toHaveTextContent("Sep 26, 2026");
    expect(screen.getByRole("combobox", { name: "Choose a release" })).toHaveValue("");
    expect(screen.getByTestId("market-watermark")).toHaveTextContent("CARD PIRATEJapanese card prices · JPY");
  });

  it("offers only 7D, 30D and ALL; 30D shows an honest unavailable state instead of a chart", async () => {
    await ready();
    const windows = within(screen.getByRole("group", { name: "Market window" }));
    expect(windows.getAllByRole("button").map((b) => b.textContent)).toEqual(["7D", "30D", "ALL"]);
    fireEvent.click(windows.getByRole("button", { name: "30D" }));
    await screen.findByText("Price movement unavailable");
    expect(screen.queryByTestId("market-movement")).not.toBeInTheDocument();
    expect(screen.queryByTestId("market-value-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("market-coverage-state")).toHaveTextContent("this 30D window");
    expect(screen.getByTestId("market-tracked-value")).toHaveTextContent("¥262,279");
    fireEvent.click(windows.getByRole("button", { name: "ALL" }));
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("ALL"));
    expect(apiGet).toHaveBeenCalledWith(BASE, { params: { release_product_id: null, window: "all" } });
  });

  it("switches to literal tracked value without another API call, and explains both modes", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "About chart modes" }));
    expect(screen.getByRole("note")).toHaveTextContent("Coverage-neutral price movement across comparable cards.");
    fireEvent.click(screen.getByRole("button", { name: "Tracked value" }));
    expect(screen.getByTestId("market-value-chart")).toHaveAttribute("data-mode", "value");
    expect(screen.getByRole("note")).toHaveTextContent("Coverage additions and removals");
    expect(apiGet.mock.calls.filter(([path]) => path === BASE)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "About tracked value" }));
    expect(screen.getByText("Value of one copy of every physical version Card Pirate currently prices in this scope.")).toBeInTheDocument();
  });

  it("withholds an ALL performance chart when the full archive crosses a break", async () => {
    apiGet.mockImplementation((path, options) => options?.params?.window === "all"
      ? Promise.resolve({ ...fixtures.all, movement: { ...fixtures.all.movement, available: false, pct: null, reason: "segment_break" } })
      : stub(path, options));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "ALL" }));
    await screen.findByText("Price movement unavailable");
    expect(screen.queryByTestId("market-value-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("market-coverage-state")).toHaveTextContent("the full archive");
    expect(document.body.textContent).not.toContain("segment_break");
  });

  it("renders genuine flat movement as zero, and never renders null JPY as zero", async () => {
    apiGet.mockImplementation((path, options) => path === BASE ? Promise.resolve({ ...fixtures.overall, movement: { ...fixtures.overall.movement, pct: "0" }, tracked_value: { ...fixtures.overall.tracked_value, value_jpy: null } }) : stub(path, options));
    await ready();
    expect(screen.getByTestId("market-movement")).toHaveTextContent("0.00%");
    expect(screen.getByTestId("market-tracked-value")).toHaveTextContent("Not yet priced");
    expect(screen.getByTestId("market-tracked-value")).not.toHaveTextContent("¥0");
  });

  it("keeps the complete five-section story without legacy endpoints", async () => {
    await ready();
    for (const text of [/Card Pirate Index/, /Market Snapshot/, /Price distribution/, /Index composition/, /Market breadth/, /Cards in this market/, /Median price/, /Release market table/]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
    expect(apiGet.mock.calls.map(([path]) => path).sort()).toEqual([BASE, `${BASE}/most-valuable`, `${BASE}/movers`, `${BASE}/releases`]);
    expect(Array.from(document.querySelectorAll("main section[data-testid]")).map((section) => section.getAttribute("data-testid"))).toEqual(["market-value-hero", "market-value-movers", "market-value-most-valuable", "market-value-comparison", "release-market"]);
    expect(screen.queryByText(/\bLive\b|\bToday\b/)).not.toBeInTheDocument();
  });
});

describe("authoritative release scope", () => {
  it("uses a shared release ID directly and shows the English name and sparse coverage", async () => {
    navigate("/analytics?release_product_id=186");
    await ready();
    expect(screen.getByRole("heading", { name: "OP-05 — Awakening of the New Era" })).toBeInTheDocument();
    expect(screen.getByText("Price coverage in progress")).toBeInTheDocument();
    expect(screen.getByTestId("market-tracked-value")).toHaveTextContent(/Tracked so far.*¥480/);
    expect(screen.getByTestId("market-tracked-value")).toHaveTextContent("4 of 154 card variants priced");
    expect(screen.getByTestId("market-tracked-value")).toHaveTextContent("2.6% coverage");
    expect(screen.queryByTestId("market-value-chart")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("新時代");
    expect(apiGet).toHaveBeenCalledWith(BASE, { params: { release_product_id: 186, window: "7d" } });
    fireEvent.click(screen.getByRole("button", { name: "Tracked value" }));
    expect(screen.getByTestId("market-value-chart")).toHaveAttribute("data-mode", "value");
  });

  it("navigates by ID, honors release-list order and lets Back/Forward restore settled scopes", async () => {
    await ready();
    const selector = screen.getByRole("combobox");
    expect(within(selector).getAllByRole("option").map((o) => o.textContent)).toEqual(["All One Piece", "OP-17 — The World's Strongest Warriors", "OP-05 — Awakening of the New Era", "OP-01 — Romance Dawn"]);
    fireEvent.change(selector, { target: { value: "181" } });
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("+4.20%"));
    expect(window.location.search).toBe("?release_product_id=181");
    act(() => window.history.back());
    await waitFor(() => expect(selector).toHaveValue(""));
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("−3.94%"));
    act(() => window.history.forward());
    await waitFor(() => expect(selector).toHaveValue("181"));
    await waitFor(() => expect(screen.getByTestId("market-movement")).toHaveTextContent("+4.20%"));
    fireEvent.change(selector, { target: { value: "" } });
    expect(window.location.pathname + window.location.search).toBe("/analytics");
  });

  it("ignores legacy set= and removes legacy parameters when selecting a release", async () => {
    navigate("/analytics?set=OP05&basis=yuyutei");
    await ready();
    expect(screen.getByTestId("market-movement")).toHaveTextContent("−3.94%");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "186" } });
    expect(window.location.search).toBe("?release_product_id=186");
  });

  it.each(["0", "-1", "bad", "1.5", "9007199254740992"])("refuses malformed scope %s without silently showing Overall", async (id) => {
    navigate(`/analytics?release_product_id=${id}`);
    await ready();
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a valid release");
    expect(apiGet.mock.calls.some(([path]) => path === BASE)).toBe(false);
  });
});

describe("loading and failures", () => {
  it("keeps the previous scope, window, chart and as_of together until the next view settles", async () => {
    await ready();
    const next = deferred<typeof fixtures.eligible>();
    apiGet.mockImplementation((path, options) => path === BASE ? next.promise : stub(path, options));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "181" } });
    expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("market-movement")).toHaveTextContent("−3.94%7D");
    expect(screen.getByRole("heading", { name: "One Piece price movement" })).toBeInTheDocument();
    expect(screen.getByTestId("market-value-chart")).toBeInTheDocument();
    await act(async () => next.resolve(fixtures.eligible));
    expect(screen.getByRole("heading", { name: "OP-01 — Romance Dawn" })).toBeInTheDocument();
    expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "false");
  });

  it("an abandoned scope response cannot overwrite a newer selection", async () => {
    await ready();
    const slow = deferred<typeof fixtures.eligible>();
    apiGet.mockImplementation((path, options) => path === BASE && options?.params?.release_product_id === 181 ? slow.promise : stub(path, options));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "181" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "186" } });
    await screen.findByText("Price coverage in progress");
    await act(async () => slow.resolve(fixtures.eligible));
    expect(screen.getByRole("heading", { name: "OP-05 — Awakening of the New Era" })).toBeInTheDocument();
    expect(screen.queryByTestId("market-movement")).not.toBeInTheDocument();
  });

  it("retains the previous window caption during a delayed window request", async () => {
    await ready();
    const slow = deferred<typeof fixtures.thirtyDay>();
    apiGet.mockImplementation((path, options) => options?.params?.window === "30d" ? slow.promise : stub(path, options));
    fireEvent.click(screen.getByRole("button", { name: "30D" }));
    expect(screen.getByTestId("market-movement")).toHaveTextContent("7D");
    expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "true");
    await act(async () => slow.resolve(fixtures.thirtyDay));
    expect(screen.queryByTestId("market-value-chart")).not.toBeInTheDocument();
  });

  it("release-list failure leaves Overall and direct release navigation usable", async () => {
    apiGet.mockImplementation((path, options) => path.endsWith("/releases") ? Promise.reject(new Error("list failed")) : stub(path, options));
    await ready();
    expect(screen.getByTestId("market-movement")).toHaveTextContent("−3.94%");
    expect(within(screen.getByTestId("market-value-hero")).getByText(/Release list unavailable/)).toBeInTheDocument();
    navigate("/analytics?release_product_id=181");
    await screen.findByRole("heading", { name: "OP-01 — Romance Dawn" });
    expect(screen.getByRole("combobox")).toHaveValue("181");
  });

  it("Market API failure stays local with a retry and usable selector", async () => {
    apiGet.mockImplementation((path, options) => path === BASE ? Promise.reject(new Error("API failed")) : stub(path, options));
    await ready();
    expect(screen.getByRole("alert")).toHaveTextContent("Market unavailable");
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeEnabled();
    apiGet.mockImplementation(stub);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByTestId("market-movement");
  });

  it("unknown release returns a local error, never an Overall fallback", async () => {
    navigate("/analytics?release_product_id=99999");
    apiGet.mockImplementation((path, options) => path === BASE ? Promise.reject(new ApiError("not found", 404)) : stub(path, options));
    await ready();
    expect(screen.getByRole("alert")).toHaveTextContent("This release could not be found.");
    expect(screen.queryByTestId("market-movement")).not.toBeInTheDocument();
  });
});

describe("B2 independent discovery requests", () => {
  it("refetches exactly hero, movers and most valuable once on release change", async () => {
    await ready();
    apiGet.mockClear();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "186" } });
    await waitFor(() => expect(screen.getByTestId("valuable-settled")).toHaveAttribute("aria-busy", "false"));
    expect(apiGet.mock.calls).toHaveLength(3);
    expect(apiGet.mock.calls).toEqual(expect.arrayContaining([
      [BASE, { params: { release_product_id: 186, window: "7d" } }],
      [`${BASE}/movers`, { params: { release_product_id: 186, order: "gainers", limit: 5 } }],
      [`${BASE}/most-valuable`, { params: { release_product_id: 186, limit: 6 } }],
    ]));
  });

  it("isolates chart modes/windows and mover modes from each other's requests", async () => {
    await ready();
    apiGet.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Tracked value" }));
    fireEvent.click(screen.getByRole("button", { name: "Price movement" }));
    expect(apiGet).not.toHaveBeenCalled();
    for (const [label, token] of [["30D", "30d"], ["ALL", "all"], ["7D", "7d"]]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "false"));
      expect(apiGet.mock.calls).toEqual([[BASE, { params: { release_product_id: null, window: token } }]]);
      apiGet.mockClear();
    }
    for (const [label, order] of [["Losers", "losers"], ["Market impact", "impact"], ["Gainers", "gainers"]]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => expect(screen.getByTestId("movers-settled")).toHaveAttribute("aria-busy", "false"));
      expect(apiGet.mock.calls).toEqual([[`${BASE}/movers`, { params: { release_product_id: null, order, limit: 5 } }]]);
      apiGet.mockClear();
    }
  });

  it.each(["movers", "most-valuable"])("keeps a %s failure and retry local", async (endpoint) => {
    apiGet.mockImplementation((path, options) => path === `${BASE}/${endpoint}` ? Promise.reject(new Error("failed")) : stub(path, options));
    await ready();
    const section = within(screen.getByTestId(`market-value-${endpoint}`));
    expect(section.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByTestId("market-value-chart")).toBeInTheDocument();
    const other = within(screen.getByTestId(`market-value-${endpoint === "movers" ? "most-valuable" : "movers"}`));
    expect(other.getAllByRole("link").length).toBeGreaterThan(4);
    apiGet.mockClear().mockImplementation(stub);
    fireEvent.click(section.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(section.queryByRole("alert")).not.toBeInTheDocument());
    expect(apiGet.mock.calls).toHaveLength(1);
    expect(apiGet.mock.calls[0][0]).toBe(`${BASE}/${endpoint}`);
  });
});

describe("B3 shared census and comparison isolation", () => {
  it("supplies scope, comparison eligibility and Release Market with one release request", async () => {
    await ready();
    expect(within(screen.getByRole("combobox")).getByRole("option", { name: "OP-01 — Romance Dawn" })).toBeInTheDocument();
    const comparison = within(screen.getByTestId("market-value-comparison"));
    fireEvent.click(comparison.getByRole("button", { name: /^Compare releases/ }));
    expect(comparison.getByRole("checkbox", { name: "OP-01 — Romance Dawn" })).toBeEnabled();
    const ineligible = comparison.getByRole("checkbox", { name: "OP-05 — Awakening of the New Era" });
    expect(ineligible).toBeDisabled();
    expect(ineligible).toHaveAccessibleDescription("Price coverage in progress");
    expect(within(screen.getByTestId("release-market")).getByRole("button", { name: "View OP-01 — Romance Dawn Market" })).toBeInTheDocument();
    expect(apiGet.mock.calls.filter(([path]) => path === `${BASE}/releases`)).toHaveLength(1);
    expect(apiGet.mock.calls).toHaveLength(4);
  });

  it("isolates comparison additions/removal and scope changes without refetching the census", async () => {
    await ready();
    const comparison = within(screen.getByTestId("market-value-comparison"));
    apiGet.mockClear();
    fireEvent.click(comparison.getByRole("button", { name: /^Compare releases/ }));
    fireEvent.click(comparison.getByRole("checkbox", { name: "OP-01 — Romance Dawn" }));
    await waitFor(() => expect(screen.getByTestId("comparison-settled")).toHaveAttribute("aria-busy", "false"));
    expect(apiGet.mock.calls).toEqual([[BASE, { params: { release_product_id: 181, window: "7d" } }]]);
    fireEvent.click(comparison.getByRole("button", { name: "Done" }));
    apiGet.mockClear();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "186" } });
    await waitFor(() => expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "false"));
    expect(apiGet.mock.calls).toHaveLength(3);
    expect(apiGet.mock.calls.map(([path]) => path).sort()).toEqual([BASE, `${BASE}/most-valuable`, `${BASE}/movers`]);
    expect(apiGet.mock.calls.every(([, options]) => options.params.release_product_id === 186)).toBe(true);
    expect(comparison.getByRole("list", { name: "Comparison legend" })).toHaveTextContent("OP-01");
    apiGet.mockClear();
    fireEvent.click(comparison.getByRole("button", { name: "Remove OP-01" }));
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("navigates release rows back to the hero by ID and searches locally", async () => {
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    await ready();
    const market = within(screen.getByTestId("release-market"));
    apiGet.mockClear();
    fireEvent.change(market.getByRole("searchbox", { name: "Search releases" }), { target: { value: "Awakening" } });
    expect(apiGet).not.toHaveBeenCalled();
    fireEvent.click(market.getByRole("button", { name: "View OP-05 — Awakening of the New Era Market" }));
    await waitFor(() => expect(screen.getByTestId("market-settled")).toHaveAttribute("aria-busy", "false"));
    expect(window.location.pathname + window.location.search).toBe("/analytics?release_product_id=186");
    expect(screen.getByRole("combobox")).toHaveValue("186");
    expect(scroll).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
    expect(apiGet.mock.calls).toHaveLength(3);
    scroll.mockRestore();
  });
});
