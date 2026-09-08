/** The Card Pirate Index hero on /analytics (TASK INDEX 2A).
 *
 * WHAT THESE TESTS ARE ACTUALLY GUARDING. The hero renders a published index,
 * and the ways to make it lie are specific, plausible, and all of them look
 * fine on screen:
 *
 *   - recompute the change from `points[]` instead of rendering the server's,
 *     which drifts the instant a cap or a minimum-constituent rule changes;
 *   - read `change.pct` as a fraction and multiply by 100, turning +0.01 %
 *     into +1.07 % - a plausible small move rather than an obvious bug;
 *   - render a null change as 0 %, which says "the market did not move" when
 *     the truth is "this period cannot be compared";
 *   - answer a window by slicing a longer series already in hand, so the high,
 *     the low and the change stop being the server's for that window;
 *   - pad a short series backward so a 1Y button looks like it has a year;
 *   - let a slow response for an abandoned window land on top of a newer one.
 *
 * Each has a test below. The fixtures use staging's real five-day shape,
 * because a flat index over five days is exactly where a wrong number is
 * hardest to spot by eye.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("next/navigation", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
    usePathname: () => "/analytics",
    useSearchParams: () => {
      const [, bump] = React.useReducer((n: number) => n + 1, 0);
      React.useEffect(() => {
        const onPop = () => bump();
        window.addEventListener("popstate", onPop);
        return () => window.removeEventListener("popstate", onPop);
      }, []);
      return new URLSearchParams(window.location.search);
    },
  };
});

const { fetchMarketBases, fetchMarketCards, fetchMarketFilters, fetchMarketOverview } =
  vi.hoisted(() => ({
    fetchMarketBases: vi.fn(),
    fetchMarketCards: vi.fn(),
    fetchMarketFilters: vi.fn(),
    fetchMarketOverview: vi.fn(),
  }));
vi.mock("@/lib/marketAnalytics", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/marketAnalytics")>("@/lib/marketAnalytics");
  return { ...actual, fetchMarketBases, fetchMarketCards, fetchMarketFilters, fetchMarketOverview };
});

/** `apiGet` is mocked, not `fetchIndexSeries`.
 *
 * The point of several tests below is WHICH TOKEN goes on the wire, and a mock
 * of the module's own fetch helper cannot prove that - it would assert the
 * page called a function with a string, not that the string reached
 * `/analytics/index?window=`. Mocking one layer lower means the window
 * grammar, the query parameter name and the path are all under test. */
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiGet };
});

import {
  INDEX_WINDOWS,
  type IndexBreak,
  type IndexPoint,
  type IndexSeries,
  type IndexWindowRow,
} from "@/lib/cardPirateIndex";

import MarketLandscapePage from "./page";

// --- fixtures ---------------------------------------------------------------

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

/** Every window reachable - what the map looks like once the archive is long
 * enough for the whole ladder. */
const ALL_AVAILABLE: IndexWindowRow[] = WINDOWS.map((row) => ({ ...row, available: true }));

function breakEntry(partial: Partial<IndexBreak> & { at: string; reason: string }): IndexBreak {
  return {
    from_methodology_version: null,
    to_methodology_version: null,
    from_index_version: null,
    to_index_version: null,
    from_source_semantics_version: null,
    to_source_semantics_version: null,
    carried: null,
    carried_level: null,
    carried_from_point_date: null,
    prior_point_date: null,
    step_days: null,
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

/** Every index request, in order. An implicit one (no `params`) is logged as
 * the literal "(no window)", so a test can assert on the ABSENCE of a token
 * rather than only on its value. */
function indexCalls() {
  return apiGet.mock.calls
    .filter((call) => call[0] === "/analytics/index")
    .map((call) => (call[1]?.params?.window as string) ?? "(no window)");
}

/** Stubs `/analytics/index` for every window.
 *
 * `windows` and `default_window` are the SERVER's now, so they are inputs to
 * the stub rather than something the page decides - which is exactly the
 * property most of these tests exist to pin. The default arrangement is
 * staging's own: five days of archive, so the server reports only `all` as
 * available and names it the default.
 */
function stubIndex(
  byWindow: Partial<Record<string, IndexSeries>> = {},
  options: { windows?: IndexWindowRow[]; defaultWindow?: string } = {},
) {
  const windows = options.windows ?? WINDOWS;
  const defaultWindow = options.defaultWindow ?? "all";
  apiGet.mockImplementation((path: string, opts?: { params?: { window?: string } }) => {
    if (path !== "/analytics/index") return Promise.reject(new Error(`unstubbed ${path}`));
    // No `params` at all is the request for the default, and the SERVER
    // resolves it - so the stub answers with `defaultWindow`, exactly as the
    // route now does. A stub that answered a fixed token here would hide the
    // very coupling TASK INDEX 2A-C removed.
    const w = opts?.params?.window ?? defaultWindow;
    const base = byWindow[w];
    if (base) {
      // Options last: a byWindow fixture supplies the series, the options
      // supply the server metadata, and a fixture built from `series()` must
      // not quietly reinstate the default map.
      return Promise.resolve({ ...base, windows, default_window: defaultWindow });
    }
    const row = windows.find((entry) => entry.token === w);
    return Promise.resolve(
      series({
        requested_window: w,
        windows,
        default_window: defaultWindow,
        // The server answers coverage with the same span test it answers
        // availability with, so the stub keeps the two consistent rather than
        // manufacturing a combination the API cannot produce.
        covers_requested_window: row ? row.available : false,
        window_start: w === "all" ? null : "2026-06-09",
      }),
    );
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/analytics");
  fetchMarketBases.mockResolvedValue({ bases: BASES });
  fetchMarketFilters.mockResolvedValue({ sets: [], rarities: [] });
  fetchMarketOverview.mockResolvedValue({
    price_basis: "market_index", kind: "market_index", source: null,
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
    index_composition: null,
  });
  fetchMarketCards.mockResolvedValue({
    items: [], total: 0, limit: 6, offset: 0,
    pagination: { next_offset: null, prev_offset: null, has_more: false },
    facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
  });
  stubIndex();
});

afterEach(() => {
  vi.clearAllMocks();
  apiGet.mockReset();
});

async function renderPage() {
  render(<MarketLandscapePage />);
  await waitFor(() => expect(screen.getByTestId("index-level")).toBeTruthy());
}

/** By ACCESSIBLE NAME, which for an unreachable window includes its reason.
 * A plain label lookup is still exact for reachable ones. */
function windowButton(label: string) {
  const group = within(screen.getByTestId("index-window"));
  const exact = group.queryByRole("button", { name: label });
  if (exact) return exact;
  return group.getByRole("button", { name: new RegExp(`^${label}( —|$)`) });
}

// --- A. the window grammar --------------------------------------------------

describe("the control is rendered from the server's window list", () => {
  it("offers exactly the tokens the server published, in the order it published them", async () => {
    await renderPage();
    const labels = within(screen.getByTestId("index-window"))
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels).toEqual(["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]);
  });

  it("renders a token this build has never heard of", async () => {
    // The list is the server's. A control that dropped an unknown token would
    // be overriding the authority 2A-B moved to the server.
    stubIndex({}, {
      windows: [windowRow("5y", true, 2000, 1825), windowRow("all", true, 2000, null)],
      defaultWindow: "all",
    });
    await renderPage();
    const labels = within(screen.getByTestId("index-window"))
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels).toEqual(["5Y", "All"]);
  });

  it("marks a window the server reports as unavailable", async () => {
    // Section 12.2 rule 3: the map exists so an unreachable timeframe renders
    // as a disabled button with a reason, not as a clickable path into a chart
    // that cannot answer it.
    await renderPage();
    for (const label of ["2W", "1M", "3M", "6M", "1Y", "2Y"]) {
      expect(windowButton(label).getAttribute("aria-disabled")).toBe("true");
    }
    expect(windowButton("All").getAttribute("aria-disabled")).toBeNull();
  });

  it("keeps an unreachable window FOCUSABLE, so its reason is not mouse-only", async () => {
    // A natively `disabled` button leaves the tab order in every major
    // browser, and `title` never fires on touch - so with six of seven windows
    // unreachable, the native form left most of this control unexplained for
    // anyone not using a mouse.
    await renderPage();
    const button = windowButton("2W");
    expect(button.hasAttribute("disabled")).toBe(false);
    button.focus();
    expect(document.activeElement).toBe(button);
  });

  it("carries the reason in the accessible name, not only in a hover title", async () => {
    await renderPage();
    const reason = "Atlas has 5 days of index history; this window needs 14.";
    expect(windowButton(`2W — ${reason}`)).toBeTruthy();
    expect(within(screen.getByTestId("index-window")).getByTitle(reason)).toBeTruthy();
  });

  it("says on screen why the unreachable windows are unreachable", async () => {
    await renderPage();
    const note = screen.getByTestId("index-window-shortfall").textContent ?? "";
    expect(note).toContain("2W");
    expect(note).toContain("2Y");
    expect(note).toContain("5 days");
    expect(note).not.toContain("All");
  });

  it("an unreachable window asks the server nothing when pressed", async () => {
    await renderPage();
    apiGet.mockClear();
    fireEvent.click(windowButton("2W"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(indexCalls()).toEqual([]);
    expect(windowButton("All").getAttribute("aria-pressed")).toBe("true");
  });

  it("shows no shortfall note when every window is reachable", async () => {
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "all" });
    await renderPage();
    expect(screen.queryByTestId("index-window-shortfall")).toBeNull();
  });

  it("never derives availability from the points or a clock", async () => {
    // Same five points, but the server says every window is spanned. A client
    // re-deriving from `available_from` would still grey six of them out.
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "3m" });
    await renderPage();
    for (const label of ["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]) {
      expect(windowButton(label).getAttribute("aria-disabled")).toBeNull();
    }
  });

  it.each([
    ["2W", "2w"],
    ["1M", "1m"],
    ["3M", "3m"],
    ["6M", "6m"],
    ["1Y", "1y"],
    ["2Y", "2y"],
    ["All", "all"],
  ])("pressing %s requests window=%s", async (label, token) => {
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "3m" });
    await renderPage();
    // Step off whatever the server opened on, so the assertion is about the
    // target press.
    const parking = label === "6M" ? "1M" : "6M";
    fireEvent.click(windowButton(parking));
    await waitFor(() => expect(windowButton(parking).getAttribute("aria-pressed")).toBe("true"));

    apiGet.mockClear();
    fireEvent.click(windowButton(label));
    await waitFor(() => expect(indexCalls()).toContain(token));
    expect(new Set(indexCalls())).toEqual(new Set([token]));
  });

  it("re-pressing the active window asks the server nothing", async () => {
    await renderPage();
    expect(windowButton("All").getAttribute("aria-pressed")).toBe("true");
    apiGet.mockClear();
    fireEvent.click(windowButton("All"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(indexCalls()).toEqual([]);
  });

  it("sends only tokens the published grammar contains", async () => {
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "3m" });
    await renderPage();
    for (const label of ["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]) {
      fireEvent.click(windowButton(label));
    }
    await waitFor(() => expect(indexCalls().length).toBeGreaterThan(1));
    // The first is the implicit request and carries no token by design; every
    // later one is an explicit selection and must be in the grammar.
    expect(indexCalls()[0]).toBe("(no window)");
    for (const token of indexCalls().slice(1)) {
      expect(INDEX_WINDOWS).toContain(token);
    }
  });

  it("marks exactly one window pressed", async () => {
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "3m" });
    await renderPage();
    fireEvent.click(windowButton("1M"));
    await waitFor(() => expect(windowButton("1M").getAttribute("aria-pressed")).toBe("true"));
    const pressed = within(screen.getByTestId("index-window"))
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
  });
});

// --- B. the default window is the server's decision -------------------------

describe("the opening request names no window, and the server answers it", () => {
  it("makes exactly ONE request, with no window parameter", async () => {
    await renderPage();
    expect(indexCalls()).toEqual(["(no window)"]);
    expect(windowButton("All").getAttribute("aria-pressed")).toBe("true");
  });

  it("opens straight on 3M when the server's default is 3M - no intermediate ALL", async () => {
    // The transition, as the client sees it: the same single request, a
    // different answer. Before TASK INDEX 2A-C this cost a bootstrap `all`
    // followed by a `3m`, and the reader saw the wrong window first.
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "3m" });
    await renderPage();
    expect(indexCalls()).toEqual(["(no window)"]);
    expect(indexCalls()).not.toContain("all");
    expect(windowButton("3M").getAttribute("aria-pressed")).toBe("true");
    expect(windowButton("All").getAttribute("aria-pressed")).toBe("false");
  });

  it("presses the window the response is about, whatever the default says", async () => {
    // `requested_window` and `default_window` diverge as soon as a reader
    // picks a window; the pressed button follows the payload, not the policy.
    stubIndex(
      { "1y": series({ requested_window: "1y", default_window: "3m" }) },
      { windows: ALL_AVAILABLE, defaultWindow: "3m" },
    );
    await renderPage();
    fireEvent.click(windowButton("1Y"));
    await waitFor(() => expect(windowButton("1Y").getAttribute("aria-pressed")).toBe("true"));
    expect(windowButton("3M").getAttribute("aria-pressed")).toBe("false");
  });

  it("never derives the opening window from dates or points", async () => {
    // Five days of points and a server that says 2W. The page has no vote.
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "2w" });
    await renderPage();
    expect(windowButton("2W").getAttribute("aria-pressed")).toBe("true");
  });

  it("holds no bootstrap, preferred or fallback window of its own", async () => {
    const fs = await import("fs/promises");
    for (const path of [
      "src/app/analytics/page.tsx",
      "src/components/ui/CardPirateIndexHero.tsx",
    ]) {
      const source = await fs.readFile(path, "utf8");
      const code = source
        .split("\n")
        .filter((line) => !line.trim().startsWith("*") && !line.trim().startsWith("//"))
        .join("\n");
      expect(code).not.toContain("BOOTSTRAP_WINDOW");
      expect(code).not.toMatch(/["'](2w|1m|3m|6m|1y|2y|all)["']/);
    }
  });
});

// --- C. the numbers are the server's ----------------------------------------

describe("every figure is rendered, not recomputed", () => {
  it("shows the level, start, high and low the server published", async () => {
    await renderPage();
    expect(screen.getByTestId("index-level").textContent).toBe("1,000.11");
    expect(screen.getByTestId("index-start").textContent).toBe("1,000.00");
    expect(screen.getByTestId("index-high").textContent).toBe("1,000.96");
    expect(screen.getByTestId("index-low").textContent).toBe("1,000.00");
  });

  it("shows the server's change, not one derived from the points", async () => {
    // The points would give 1000.1065 - 1000.0000 = +0.1065 too, so a
    // recomputing client passes a naive assertion. This fixture breaks the tie:
    // the server publishes a DIFFERENT change from the one the endpoints imply,
    // and only the server's may be rendered.
    stubIndex({
      all: series({
        change: {
          absolute: "12.3400", pct: "1.234000",
          from_date: "2026-09-03", to_date: "2026-09-07", spans_break: false,
        },
      }),
    });
    await renderPage();
    const readout = screen.getByTestId("index-change").textContent ?? "";
    expect(readout).toContain("+12.34");
    expect(readout).toContain("1.23%");
    expect(readout).not.toContain("0.11");
  });

  it("reads change.pct as percent units, never as a fraction", async () => {
    await renderPage();
    // pct "0.010650" beside absolute "0.1065" on a 1000 base is 0.01 %.
    // A client multiplying by 100 would print 1.07% - plausible, and wrong by
    // two orders of magnitude.
    const readout = screen.getByTestId("index-change").textContent ?? "";
    expect(readout).toContain("0.01%");
    expect(readout).not.toContain("1.07%");
    expect(readout).not.toContain("1.065%");
  });

  it("marks a change that spans a methodology break", async () => {
    stubIndex({
      all: series({
        change: {
          absolute: "0.1065", pct: "0.010650",
          from_date: "2026-09-03", to_date: "2026-09-07", spans_break: true,
        },
      }),
    });
    await renderPage();
    // Shown, never suppressed - it is a legitimate linked-index return - but
    // never as a bare percentage either.
    expect(screen.getByTestId("index-change-break")).toBeTruthy();
    expect(screen.getByTestId("index-change").textContent).toContain("0.01%");
  });
});

describe("an unavailable change is an absence, not a zero", () => {
  it("says so in words and prints no percentage", async () => {
    stubIndex({
      all: series({ change: null, change_unavailable_reason: "single_point_window" }),
    });
    await renderPage();
    const hero = screen.getByTestId("index-hero");
    expect(screen.getByTestId("index-change-unavailable").textContent).toMatch(
      /not available/i,
    );
    expect(screen.queryByTestId("index-change")).toBeNull();
    // The level still renders; it is the CHANGE that is unavailable.
    expect(screen.getByTestId("index-level").textContent).toBe("1,000.11");
    // No "0%", no "0.00%", and no bare dash standing in for one.
    const headline = hero.textContent ?? "";
    expect(headline).not.toMatch(/[+−-]?0\.00\s*%/);
    expect(headline).not.toMatch(/(^|\s)0%/);
  });

  it("does not fall back to a shorter window to manufacture one", async () => {
    stubIndex({
      all: series({ change: null, change_unavailable_reason: "single_point_window" }),
    });
    await renderPage();
    apiGet.mockClear();
    // Nothing may go out looking for a window that would have a change.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(indexCalls()).toEqual([]);
  });
});

// --- D. partial history -----------------------------------------------------

describe("partial coverage is data reality, not a policy decision", () => {
  /** The distinction the brief draws, and the reason both survive: the DEFAULT
   * is server policy, and partial coverage is a fact about the archive. A
   * window the server calls available can still come back covering less than
   * it asked for - and the page must draw what exists and say so, never
   * silently substitute `all`. */
  const PARTIAL = { windows: ALL_AVAILABLE, defaultWindow: "all" };

  it("draws the available series and names the span it actually covers", async () => {
    stubIndex(
      { "1y": series({ requested_window: "1y", covers_requested_window: false,
        window_start: "2025-09-07" }) },
      PARTIAL,
    );
    await renderPage();
    fireEvent.click(windowButton("1Y"));
    await waitFor(() => expect(screen.getByTestId("index-partial-history")).toBeTruthy());
    const note = screen.getByTestId("index-partial-history").textContent ?? "";
    expect(note).toMatch(/available history only/i);
    expect(note).toContain("Sep 3");
    expect(note).toContain("Sep 7, 2026");
    expect(note).toContain("a year");
    expect(screen.getByTestId("index-chart")).toBeTruthy();
    expect(screen.getByTestId("index-level").textContent).toBe("1,000.11");
  });

  it("does NOT silently switch back to All", async () => {
    stubIndex(
      { "2y": series({ requested_window: "2y", covers_requested_window: false,
        window_start: "2024-09-07" }) },
      PARTIAL,
    );
    await renderPage();
    fireEvent.click(windowButton("2Y"));
    await waitFor(() => expect(screen.getByTestId("index-partial-history")).toBeTruthy());
    expect(windowButton("2Y").getAttribute("aria-pressed")).toBe("true");
    expect(windowButton("All").getAttribute("aria-pressed")).toBe("false");
    // The opening request named no window at all, so nothing may have asked
    // for `all` - not before the reader chose 2Y, and not after.
    expect(indexCalls()).toEqual(["(no window)", "2y"]);
  });

  it("does not make the control look broken", async () => {
    stubIndex(
      { "2y": series({ requested_window: "2y", covers_requested_window: false }) },
      PARTIAL,
    );
    await renderPage();
    fireEvent.click(windowButton("2Y"));
    await waitFor(() => expect(screen.getByTestId("index-partial-history")).toBeTruthy());
    for (const label of ["2W", "1M", "3M", "6M", "1Y", "2Y", "All"]) {
      expect(windowButton(label).getAttribute("aria-disabled")).toBeNull();
    }
  });

  it("shows no partial-history note when the window IS covered", async () => {
    await renderPage();
    expect(screen.queryByTestId("index-partial-history")).toBeNull();
    expect(screen.getByTestId("index-covered-range").textContent).toContain("Sep 7, 2026");
  });

  it("drops the duration clause for `all`, which is not a duration", async () => {
    stubIndex({ all: series({ requested_window: "all", covers_requested_window: false }) });
    await renderPage();
    const note = screen.getByTestId("index-partial-history").textContent ?? "";
    expect(note).toMatch(/available history only/i);
    expect(note).not.toMatch(/for a full/i);
    expect(note).not.toMatch(/\bAll\b yet/);
  });
});

// --- E. nothing is invented -------------------------------------------------

/** Recharts inside a ResponsiveContainer measures 0 in jsdom and draws no
 * path, so "no point is invented" and "a gap is never a solid daily line"
 * cannot be asserted through the DOM here. They are asserted in
 * lib/cardPirateIndex.test.ts against `splitRuns` and `indexDomain`, where the
 * geometry is decided - the same division PrintPriceHistory.test.tsx already
 * keeps with lib/printSeries.test.ts. What IS layout-independent is asserted
 * below. */
describe("the chart is present, and is not drawn over nothing", () => {
  it("renders a chart region for a series that has points", async () => {
    await renderPage();
    expect(screen.getByTestId("index-chart")).toBeTruthy();
    expect(screen.queryByTestId("index-chart-empty")).toBeNull();
  });

  it("renders an honest empty state instead of an empty chart", async () => {
    stubIndex({
      all: series({
        points: [], starting_value: null, current_value: null,
        low_value: null, high_value: null, change: null,
        available_from: null, available_to: null,
        change_unavailable_reason: "no_points",
      }),
    });
    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByTestId("index-chart-empty")).toBeTruthy());
    expect(screen.queryByTestId("index-chart")).toBeNull();
    // An empty series is not a zero level either.
    expect(screen.getByTestId("index-level").textContent).toBe("\u2014");
  });

  it("a window with less history than it asks for still draws its series", async () => {
    stubIndex(
      { "2y": series({ requested_window: "2y", covers_requested_window: false }) },
      { windows: ALL_AVAILABLE, defaultWindow: "all" },
    );
    await renderPage();
    fireEvent.click(windowButton("2Y"));
    await waitFor(() => expect(screen.getByTestId("index-partial-history")).toBeTruthy());
    // Drawn from what exists, not padded backward to two years.
    expect(screen.getByTestId("index-chart")).toBeTruthy();
    expect(screen.getByTestId("index-start").textContent).toBe("1,000.00");
  });
});

// --- F. staleness -----------------------------------------------------------

describe("a stale response cannot overwrite a newer window", () => {
  it("keeps the newer selection when an older request resolves last", async () => {
    stubIndex({}, { windows: ALL_AVAILABLE, defaultWindow: "all" });
    await renderPage();

    let resolveSlow: ((value: IndexSeries) => void) | null = null;
    apiGet.mockImplementation((path: string, options?: { params?: { window?: string } }) => {
      const w = options?.params?.window;
      if (w === "2w") {
        return new Promise<IndexSeries>((resolve) => {
          resolveSlow = resolve;
        });
      }
      return Promise.resolve(
        series({ requested_window: w, current_value: "1234.0000", change: null }),
      );
    });

    // Press the slow window, then move on before it lands.
    fireEvent.click(windowButton("2W"));
    fireEvent.click(windowButton("1M"));
    await waitFor(() => expect(screen.getByTestId("index-level").textContent).toBe("1,234.00"));

    // The abandoned 2W response arrives last, carrying a different level.
    resolveSlow!(series({ requested_window: "2w", current_value: "9999.0000" }));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.getByTestId("index-level").textContent).toBe("1,234.00");
    expect(windowButton("1M").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("the control does not exist before the server publishes its list", () => {
  it("renders no window buttons while the bootstrap is in flight", async () => {
    // This is what replaced a guard against a load-time race. The control used
    // to be built from a hardcoded token list, so it was live and pressable
    // before anything was known - and a reader who pressed 1Y then could be
    // moved back when the opening window resolved. Rendering the control from
    // the server's list removes the race at its source: there is nothing to
    // press until the vocabulary is known.
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    apiGet.mockImplementation(async () => {
      await gate;
      return series({ requested_window: "all" });
    });

    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByTestId("index-window")).toBeTruthy());
    expect(within(screen.getByTestId("index-window")).queryAllByRole("button")).toHaveLength(0);

    release!();
    await waitFor(() => expect(screen.getByTestId("index-level")).toBeTruthy());
    expect(within(screen.getByTestId("index-window")).getAllByRole("button")).toHaveLength(7);
  });

  it("reserves the control's height so it does not push the heading around", async () => {
    // The control appearing is a real layout event; the row it lives in keeps
    // its height from the first frame so the H1 beside it does not move.
    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByTestId("index-window")).toBeTruthy());
    expect(screen.getByTestId("index-window").className).toContain("min-h-");
  });
});

/** Section 13.4, and the reason it is server-authored. */
describe("a methodology break is marked from the server's own metadata", () => {
  const BREAK = breakEntry({
    at: "2026-09-05",
    reason: "index_version_change",
    from_index_version: 3,
    to_index_version: 4,
    carried: true,
    carried_level: "1000.9577",
    carried_from_point_date: "2026-09-04",
    prior_point_date: "2026-09-04",
  });

  it("names the change, the date and the carried level in text", async () => {
    stubIndex({ all: series({ breaks: [BREAK] }) });
    await renderPage();
    const note = screen.getByTestId("index-break-note").textContent ?? "";
    expect(note).toContain("Sep 5, 2026");
    expect(note).toContain("Index version 3 → 4");
    expect(note).toContain("1,000.96");
    // The frozen sentence's substance - section 13.4.
    expect(note).toMatch(/chain-linked across this point/i);
    expect(note).toMatch(/not directly comparable/i);
  });

  it("says a RESET is not comparable, rather than chain-linked", async () => {
    stubIndex({
      all: series({
        breaks: [breakEntry({
          at: "2026-09-05", reason: "index_version_change",
          from_index_version: 3, to_index_version: 4, carried: false,
        })],
      }),
    });
    await renderPage();
    const note = screen.getByTestId("index-break-note").textContent ?? "";
    expect(note).toMatch(/restarted at its base level/i);
    expect(note).not.toMatch(/chain-linked/i);
  });

  it("marks a reason this build does not recognise rather than dropping it", async () => {
    // Section 13.4: "Never hide a marker because the chart is crowded ...
    // never drop one." An unknown reason is a boundary too.
    stubIndex({ all: series({ breaks: [breakEntry({ at: "2026-09-05", reason: "future_kind" })] }) });
    await renderPage();
    expect(screen.getByTestId("index-break-note").textContent).toContain("future_kind");
  });

  it("does not treat a snapshot gap as a methodology change", async () => {
    // A gap is a cadence fact. Section 13.4 dashes the join and says nothing
    // about the measurement having changed.
    stubIndex({
      all: series({
        breaks: [breakEntry({
          at: "2026-09-05", reason: "snapshot_gap",
          prior_point_date: "2026-09-03", step_days: 2,
        })],
      }),
    });
    await renderPage();
    expect(screen.queryByTestId("index-break-note")).toBeNull();
  });

  it("shows no break note when the series has none", async () => {
    await renderPage();
    expect(screen.queryByTestId("index-break-note")).toBeNull();
  });

  it("never infers a break from the points", async () => {
    // Adjacent points, a level that jumps, and an empty `breaks` array. A
    // client inferring from geometry would mark this; the server says there is
    // no boundary, and the server is the authority.
    stubIndex({
      all: series({
        breaks: [],
        points: [
          point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
          point({ date: "2026-09-04", value: "1400.0000" }),
        ],
      }),
    });
    await renderPage();
    expect(screen.queryByTestId("index-break-note")).toBeNull();
  });
});

// --- G. what the page no longer shows ---------------------------------------

describe("'Cards in this view' is not part of the index experience", () => {
  it("renders nowhere on /analytics", async () => {
    await renderPage();
    expect(screen.queryByText("Cards in this view")).toBeNull();
    expect(document.body.textContent).not.toMatch(/a few of the priced prints counted above/i);
  });

  it("does not even request the card strip", async () => {
    await renderPage();
    expect(fetchMarketCards).not.toHaveBeenCalled();
  });

  it("leaves the reusable component in the tree for other owners", async () => {
    // The brief removes the INTEGRATION, not the component: CardImageFrame's
    // own suite still asserts MarketLandscapeCards shares its framing contract.
    const fs = await import("fs/promises");
    const source = await fs.readFile("src/components/ui/MarketLandscapeCards.tsx", "utf8");
    expect(source).toContain("export function MarketLandscapeCards");
  });
});

// --- H. the watermark is decoration ----------------------------------------

describe("the brand watermark carries no chart meaning", () => {
  it("is hidden from assistive technology", async () => {
    await renderPage();
    const mark = screen.getByTestId("index-watermark");
    expect(mark.getAttribute("aria-hidden")).toBe("true");
    // The mark itself, not just its wrapper - AtlasMark renders an <svg> that
    // would otherwise expose a <title> as an accessible name.
    expect(mark.querySelector("svg")?.getAttribute("role")).toBeNull();
    expect(mark.querySelector("title")).toBeNull();
  });

  it("does not intercept pointer events over the plot", async () => {
    await renderPage();
    expect(screen.getByTestId("index-watermark").className).toContain("pointer-events-none");
  });

  it("reuses the Atlas mark rather than inventing a second logo", async () => {
    const fs = await import("fs/promises");
    const source = await fs.readFile("src/components/ui/CardPirateIndexHero.tsx", "utf8");
    expect(source).toContain('from "@/components/brand/AtlasMark"');
    // No hand-drawn path, no text stand-in, no image asset.
    expect(source).not.toMatch(/<img\b/);
    expect(source).not.toMatch(/<path\b/);
  });

  it("does not replace the chart's own semantics", async () => {
    await renderPage();
    // The watermark sits BESIDE the chart region, never inside it as a stand-in
    // for the plotted data: the chart still renders on its own, and the level
    // and change are read from the hero's own elements rather than from a mark.
    expect(screen.getByTestId("index-chart")).toBeTruthy();
    expect(screen.getByTestId("index-watermark").querySelector('[data-testid="index-chart"]'))
      .toBeNull();
    expect(screen.getByTestId("index-level").textContent).toBe("1,000.11");
  });
});

// --- I. hierarchy -----------------------------------------------------------

describe("the index establishes the page hierarchy", () => {
  it("is the page's H1, above the market landscape section", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Card Pirate Index");
    expect(screen.getByRole("heading", { level: 2, name: "Current market landscape" })).toBeTruthy();
  });

  it("puts the chart before the coverage statistics in document order", async () => {
    await renderPage();
    const hero = screen.getByTestId("index-hero");
    const landscape = screen.getByRole("heading", { level: 2, name: "Current market landscape" });
    expect(hero.compareDocumentPosition(landscape) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
