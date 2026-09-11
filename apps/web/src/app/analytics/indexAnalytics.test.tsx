/** The What’s in the index and How many moved? panels on /analytics.
 *
 * WHAT THIS SUITE IS FOR. Both panels restate numbers the server already
 * published, so the failure mode worth guarding is not "the layout broke" but
 * "the client started producing figures of its own". Hence the emphasis on
 * request counts, on the timeframe control being unable to reach the
 * composition, and on the panels rendering the exact strings the API sent.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("next/navigation", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    usePathname: () => "/analytics",
    useSearchParams: () => {
      const [, force] = React.useState(0);
      React.useEffect(() => {
        const onPop = () => force((n: number) => n + 1);
        window.addEventListener("popstate", onPop);
        return () => window.removeEventListener("popstate", onPop);
      }, []);
      return new URLSearchParams(window.location.search);
    },
    useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  };
});

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiGet };
});

import MarketLandscapePage from "./page";
import type { IndexComposition, IndexPoint, IndexSeries, IndexWindowRow } from "@/lib/cardPirateIndex";

const WINDOWS: IndexWindowRow[] = [
  { token: "2w", available: false, covered_days: 5, required_days: 14 },
  { token: "1m", available: false, covered_days: 5, required_days: 30 },
  { token: "3m", available: false, covered_days: 5, required_days: 90 },
  { token: "6m", available: false, covered_days: 5, required_days: 180 },
  { token: "1y", available: false, covered_days: 5, required_days: 365 },
  { token: "2y", available: false, covered_days: 5, required_days: 730 },
  { token: "all", available: true, covered_days: 5, required_days: null },
];
const ALL_AVAILABLE: IndexWindowRow[] = WINDOWS.map((w) => ({ ...w, available: true }));

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
    points: [point({ date: "2026-09-06", value: "1000.9577" }), point()],
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

/** Staging's real composition on 2026-09-07. */
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

const BASES = [
  {
    key: "market_index", kind: "market_index" as const, source: null,
    reference_type: null, evidence_type: null, available: true,
    unavailable_reason: null, usable_priced_prints: 296,
  },
];

const OVERVIEW = {
  price_basis: "market_index", kind: "market_index" as const, source: null,
  reference_type: null, evidence_type: null, available: true, unavailable_reason: null,
  scope: { active_prints: 4316, set: null, rarity: null },
  coverage: {
    observed_prints: null, usable_priced_prints: 305, coverage_pct: 7.07,
    excluded_constrained_prints: null, unavailable_prints: 4011,
  },
  current_price: {
    constituent_count: 305, median_jpy: 80, p10_jpy: 30, p90_jpy: 220,
    unavailable_reason: null,
  },
  distribution: [],
  index_composition: { single_source_prints: 296, multi_source_prints: 9 },
};

/** Every request path, in order - so a test can assert on what was NOT asked
 * for as easily as on what was. */
function calls(path: string) {
  return apiGet.mock.calls.filter((c) => c[0] === path);
}

function stub({
  comp = composition(),
  compFails = false,
  ser = series(),
  windows = WINDOWS,
}: {
  comp?: IndexComposition;
  compFails?: boolean;
  ser?: IndexSeries;
  windows?: IndexWindowRow[];
} = {}) {
  apiGet.mockImplementation((path: string, opts?: { params?: { window?: string } }) => {
    if (path === "/analytics/index/composition") {
      return compFails
        ? Promise.reject(new Error("boom"))
        : Promise.resolve(comp);
    }
    if (path === "/analytics/index") {
      const w = opts?.params?.window ?? "all";
      return Promise.resolve({ ...ser, requested_window: w, windows });
    }
    if (path === "/analytics/market/bases") return Promise.resolve({ bases: BASES });
    if (path === "/analytics/market/filters") {
      return Promise.resolve({ sets: [], rarities: [] });
    }
    if (path === "/analytics/market/overview") return Promise.resolve(OVERVIEW);
    return Promise.reject(new Error(`unstubbed ${path}`));
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/analytics");
  apiGet.mockReset();
  stub();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function renderPage() {
  render(<MarketLandscapePage />);
  await waitFor(() => expect(screen.getByTestId("composition-count")).toBeTruthy());
}

function windowButton(label: string) {
  const group = within(screen.getByTestId("index-window"));
  const exact = group.queryByRole("button", { name: label });
  if (exact) return exact;
  return group.getByRole("button", { name: new RegExp(`^${label}( —|$)`) });
}

// --- A. request discipline ---------------------------------------------------

describe("the composition is fetched once and never again", () => {
  it("makes exactly one composition request on load", async () => {
    await renderPage();
    expect(calls("/analytics/index/composition")).toHaveLength(1);
  });

  it("sends no parameters with it", async () => {
    await renderPage();
    expect(apiGet).toHaveBeenCalledWith("/analytics/index/composition");
  });

  it("does NOT refetch when the reader switches timeframe", async () => {
    stub({ windows: ALL_AVAILABLE });
    await renderPage();
    for (const label of ["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]) {
      fireEvent.click(windowButton(label));
    }
    await waitFor(() =>
      expect(windowButton("All").getAttribute("aria-pressed")).toBe("true"),
    );
    expect(calls("/analytics/index/composition")).toHaveLength(1);
  });

  it("keeps the composition numbers identical across a timeframe change", async () => {
    stub({ windows: ALL_AVAILABLE });
    await renderPage();
    const before = screen.getByTestId("composition-legend").textContent;
    fireEvent.click(windowButton("1Y"));
    await waitFor(() =>
      expect(windowButton("1Y").getAttribute("aria-pressed")).toBe("true"),
    );
    expect(screen.getByTestId("composition-legend").textContent).toBe(before);
    expect(screen.getByTestId("composition-count").textContent).toBe("296");
  });

  it("never asks /analytics/market/overview for composition", async () => {
    await renderPage();
    // The overview IS requested for the section further down the page, but it
    // is not what either panel here reads - and its `index_composition` is
    // live single/multi-source state, not the archived constituent set.
    expect(screen.getByTestId("composition-count").textContent).toBe("296");
    expect(screen.queryByText(/single.source/i)).toBeNull();
    expect(screen.queryByText(/multi.source/i)).toBeNull();
  });

  it("issues no extra index request for breadth", async () => {
    await renderPage();
    expect(calls("/analytics/index")).toHaveLength(1);
    expect(calls("/analytics/index")[0][1]).toBeUndefined();
  });

  it("asks for no catalogue endpoint to build either panel", async () => {
    await renderPage();
    for (const path of ["/prints", "/cards", "/analytics/index/constituents"]) {
      expect(calls(path)).toHaveLength(0);
    }
  });
});

// --- B. composition renders the server's data --------------------------------

describe("the composition panel restates the server's numbers", () => {
  it("shows the heading and supporting copy", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { name: "What’s in the index" })).toBeTruthy();
    expect(
      screen.getByText("Cards in the index, by rarity."),
    ).toBeTruthy();
  });

  it("puts the constituent count in the middle of the donut", async () => {
    await renderPage();
    expect(screen.getByTestId("composition-count").textContent).toBe("296");
    expect(screen.getByTestId("composition-donut")).toBeTruthy();
  });

  it("renders every bucket's label, count and the SERVER's pct", async () => {
    await renderPage();
    const legend = screen.getByTestId("composition-legend").textContent ?? "";
    for (const [label, count, pct] of [
      ["C", "134", "45.27%"],
      ["R", "70", "23.65%"],
      ["UC", "69", "23.31%"],
      ["SR", "10", "3.38%"],
      ["L", "7", "2.36%"],
      ["SP CARD", "6", "2.03%"],
    ]) {
      expect(legend).toContain(label);
      expect(legend).toContain(count);
      expect(legend).toContain(pct);
    }
  });

  it("does not recompute a percentage from the count", async () => {
    // The server says 45.27 for 134/296. A client recomputing would get
    // 45.27027... and, rounded its own way, could print 45.3 or 45.27027.
    // The published string is what appears.
    stub({ comp: composition({ rarity: [{ key: "C", label: "C", count: 134, pct: 12.34 }] }) });
    await renderPage();
    const legend = screen.getByTestId("composition-legend").textContent ?? "";
    expect(legend).toContain("12.34%");
    expect(legend).not.toContain("45.27");
  });

  it("does not force the percentages to total exactly 100", async () => {
    stub({
      comp: composition({
        constituent_count: 281,
        rarity: [
          { key: "C", label: "C", count: 134, pct: 47.69 },
          { key: "UC", label: "UC", count: 69, pct: 24.56 },
          { key: "R", label: "R", count: 54, pct: 19.22 },
          { key: "SR", label: "SR", count: 10, pct: 3.56 },
          { key: "L", label: "L", count: 7, pct: 2.49 },
          { key: "SP CARD", label: "SP CARD", count: 6, pct: 2.14 },
          { key: "SEC", label: "SEC", count: 1, pct: 0.36 },
        ],
      }),
    });
    await renderPage();
    const legend = screen.getByTestId("composition-legend").textContent ?? "";
    // These total 100.02 and are printed unchanged.
    expect(legend).toContain("47.69%");
    expect(legend).toContain("0.36%");
  });

  it("renders an UNKNOWN bucket exactly like any other", async () => {
    stub({
      comp: composition({
        constituent_count: 12,
        rarity: [
          { key: "C", label: "C", count: 11, pct: 91.67 },
          { key: "UNKNOWN", label: "Unknown", count: 1, pct: 8.33 },
        ],
      }),
    });
    await renderPage();
    const legend = screen.getByTestId("composition-legend").textContent ?? "";
    expect(legend).toContain("Unknown");
    expect(legend).toContain("8.33%");
    expect(screen.getByTestId("composition-count").textContent).toBe("12");
  });

  it("carries the as-of date and names the rarity caveat", async () => {
    await renderPage();
    const meta = screen.getByTestId("composition-meta").textContent ?? "";
    expect(meta).toContain("Sep 7, 2026");
    expect(meta).toContain("Rarity uses current catalogue classification.");
    // It must NOT claim the historical labels were archived.
    expect(meta).not.toMatch(/archiv/i);
  });

  it("offers a textual equivalent of the donut", async () => {
    await renderPage();
    const summary = screen.getByTestId("composition-summary").textContent ?? "";
    expect(summary).toContain("296 constituents");
    expect(summary).toContain("C 134 (45.27%)");
    expect(screen.getByTestId("composition-donut").getAttribute("aria-hidden")).toBe(
      "true",
    );
  });
});

// --- C. composition edge cases ----------------------------------------------

describe("composition edge cases are handled honestly", () => {
  it("renders an empty state, not an empty donut, at zero constituents", async () => {
    stub({ comp: composition({ constituent_count: 0, rarity: [], as_of: "2026-09-03" }) });
    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByTestId("composition-empty")).toBeTruthy());
    expect(screen.queryByTestId("composition-donut")).toBeNull();
    expect(screen.queryByTestId("composition-count")).toBeNull();
  });

  it("shows a quiet unavailable line when the request fails", async () => {
    stub({ compFails: true });
    render(<MarketLandscapePage />);
    await waitFor(() =>
      expect(screen.getByTestId("composition-unavailable")).toBeTruthy(),
    );
    expect(screen.queryByTestId("composition-donut")).toBeNull();
  });

  it("fabricates no counts while loading", async () => {
    let resolve: ((v: IndexComposition) => void) | null = null;
    apiGet.mockImplementation((path: string) => {
      if (path === "/analytics/index/composition") {
        return new Promise<IndexComposition>((r) => {
          resolve = r;
        });
      }
      if (path === "/analytics/index") return Promise.resolve(series());
      if (path === "/analytics/market/bases") return Promise.resolve({ bases: BASES });
      if (path === "/analytics/market/filters") {
        return Promise.resolve({ sets: [], rarities: [] });
      }
      if (path === "/analytics/market/overview") return Promise.resolve(OVERVIEW);
      return Promise.reject(new Error(path));
    });
    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByTestId("index-composition")).toBeTruthy());
    expect(screen.queryByTestId("composition-count")).toBeNull();
    expect(screen.queryByTestId("composition-legend")).toBeNull();
    expect(screen.getByTestId("index-composition").textContent).not.toMatch(/\d\d+%/);
    resolve!(composition());
    await waitFor(() =>
      expect(screen.getByTestId("composition-count").textContent).toBe("296"),
    );
  });

  it("reserves the panel's height before the response lands", async () => {
    await renderPage();
    // Both panels carry the same min-height, so the row does not resize when
    // the slower of the two arrives.
    for (const id of ["index-composition", "market-breadth"]) {
      expect(screen.getByTestId(id).className).toContain("min-h-[268px]");
    }
  });

  it("a composition failure does not hide breadth or the rest of the page", async () => {
    stub({ compFails: true });
    render(<MarketLandscapePage />);
    await waitFor(() =>
      expect(screen.getByTestId("composition-unavailable")).toBeTruthy(),
    );
    expect(screen.getByTestId("breadth-up").textContent).toBe("1");
    expect(screen.getByTestId("breadth-down").textContent).toBe("3");
    expect(screen.getByTestId("breadth-flat").textContent).toBe("292");
    expect(screen.getByTestId("index-level")).toBeTruthy();
    expect(
      screen.getByRole("heading", { level: 2, name: "Prices across the catalogue" }),
    ).toBeTruthy();
  });
});

// --- D. breadth reads the newest index point ---------------------------------

describe("market breadth comes from the index series already loaded", () => {
  it("shows the heading and supporting copy", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { name: "How many moved?" })).toBeTruthy();
    expect(
      screen.getByText("How many cards moved since the previous index update."),
    ).toBeTruthy();
  });

  it("renders up, down and unchanged from the NEWEST point", async () => {
    stub({
      ser: series({
        points: [
          point({ date: "2026-09-06", movers_up: 99, movers_down: 99, movers_flat: 99 }),
          point({ date: "2026-09-07", movers_up: 1, movers_down: 3, movers_flat: 292 }),
        ],
      }),
    });
    await renderPage();
    expect(screen.getByTestId("breadth-up").textContent).toBe("1");
    expect(screen.getByTestId("breadth-down").textContent).toBe("3");
    expect(screen.getByTestId("breadth-flat").textContent).toBe("292");
  });

  it("sizes the bar from the counts and the constituent count", async () => {
    await renderPage();
    const width = (k: string) =>
      (screen.getByTestId(`breadth-bar-${k}`) as HTMLElement).style.width;
    expect(width("up")).toBe(`${(1 / 296) * 100}%`);
    expect(width("down")).toBe(`${(3 / 296) * 100}%`);
    expect(width("flat")).toBe(`${(292 / 296) * 100}%`);
  });

  it("survives a zero constituent count without NaN widths", async () => {
    stub({
      ser: series({
        points: [
          point({
            constituent_count: 0, movers_up: 0, movers_down: 0, movers_flat: 0,
            eligible_print_count: 0, capped_count: 0,
          }),
        ],
      }),
    });
    await renderPage();
    for (const k of ["up", "down", "flat"]) {
      const w = (screen.getByTestId(`breadth-bar-${k}`) as HTMLElement).style.width;
      expect(w).toBe("0%");
      expect(w).not.toContain("NaN");
    }
  });

  it("states the two counts without narrating the gap between them", async () => {
    await renderPage();
    const panel = screen.getByTestId("market-breadth").textContent ?? "";
    expect(panel).toContain("305");
    expect(panel).toContain("priced on the latest published day");
    expect(panel).toContain("296");
    expect(panel).toContain("comparable with the prior index point");
    // The REASONS for 305 > 296 are not persisted on the point, so the panel
    // must not name any of them.
    for (const invented of [
      "excluded", "entrant", "version mismatch", "churn", "dropped", "ineligible",
    ]) {
      expect(panel.toLowerCase()).not.toContain(invented);
    }
  });

  it("shows the capped line only when something was capped", async () => {
    await renderPage();
    expect(screen.getByTestId("breadth-capped").textContent).toContain("2");
    expect(screen.getByTestId("breadth-capped").textContent).toContain(
      "moves capped by index methodology",
    );
  });

  it("omits the capped line entirely at zero rather than printing 0", async () => {
    stub({ ser: series({ points: [point({ capped_count: 0 })] }) });
    await renderPage();
    expect(screen.queryByTestId("breadth-capped")).toBeNull();
    expect(screen.getByTestId("market-breadth").textContent).not.toContain("capped");
  });

  it("says so plainly on a base point, which has no breadth at all", async () => {
    stub({
      ser: series({
        points: [
          point({
            date: "2026-09-03", is_base: true, prior_point_date: null, step_days: null,
            constituent_count: 0, movers_up: null, movers_down: null,
            movers_flat: null, capped_count: null,
          }),
        ],
      }),
    });
    await renderPage();
    expect(screen.getByTestId("breadth-unavailable").textContent).toContain(
      "no prior point to compare against",
    );
    expect(screen.queryByTestId("breadth-bar")).toBeNull();
  });

  it("offers a textual equivalent of the bar", async () => {
    await renderPage();
    const summary = screen.getByTestId("breadth-summary").textContent ?? "";
    expect(summary).toContain("296");
    expect(summary).toContain("1 moved");
    expect(summary).toContain("3 moved");
    expect(summary).toContain("292 were unchanged");
    expect(screen.getByTestId("breadth-bar").getAttribute("aria-hidden")).toBe("true");
  });
});

// --- E. layout and hierarchy -------------------------------------------------

describe("the row reads as secondary analysis below the hero", () => {
  it("sits after the index hero in document order", async () => {
    await renderPage();
    const hero = screen.getByTestId("index-hero");
    const row = screen.getByTestId("index-analytics-row");
    expect(hero.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sits before the market landscape section", async () => {
    await renderPage();
    const row = screen.getByTestId("index-analytics-row");
    const landscape = screen.getByRole("heading", {
      level: 2, name: "Prices across the catalogue",
    });
    expect(row.compareDocumentPosition(landscape) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("is one column on mobile and two from lg up", async () => {
    await renderPage();
    const cls = screen.getByTestId("index-analytics-row").className;
    expect(cls).toContain("grid-cols-1");
    expect(cls).toContain("lg:grid-cols-2");
  });

  it("keeps both panel headings below the H1 in the heading hierarchy", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Card Pirate Index",
    );
    for (const name of ["What’s in the index", "How many moved?"]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeTruthy();
    }
  });

  it("leaves the hero's own controls untouched", async () => {
    await renderPage();
    const labels = within(screen.getByTestId("index-window"))
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels).toEqual(["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]);
    expect(screen.getByTestId("index-export")).toBeTruthy();
    expect(screen.getByTestId("index-chart")).toBeTruthy();
  });

  it("puts no card artwork or second brand mark inside the panels", async () => {
    await renderPage();
    for (const id of ["index-composition", "market-breadth"]) {
      const panel = screen.getByTestId(id);
      expect(panel.querySelector("img")).toBeNull();
      expect(panel.querySelector("[data-testid='index-watermark']")).toBeNull();
      expect(panel.textContent).not.toContain("CardPirate Atlas");
    }
  });
});
