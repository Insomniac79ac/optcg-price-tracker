/** The current market landscape (/analytics), Analytics 1A-B.
 *
 * Almost every assertion here is about HONESTY rather than layout. The page's
 * whole job is to report four coverage counts and three price statistics that
 * the API has already decided, and the ways to get that wrong are specific and
 * repeatable: render a null as 0, collapse a source's observed count into its
 * usable one, let a ¥1,000 platform floor reach a median, hardcode a platform,
 * or decode a stored price_type. Each of those has a test below, and several
 * are written so they would fail on a plausible refactor rather than only on
 * the exact bug that prompted them.
 *
 * The fixtures use staging's real shape - SNKRDUNK's 43 observed / 25 usable /
 * 18 excluded, Yuyu-Tei's sale-priced prints that are eligible and therefore
 * NOT excluded - because those two are the cases where a wrong number looks
 * most plausible.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

/** A faithful stand-in for the App Router's `useSearchParams`: it reads the
 * REAL window location and re-renders on `popstate`.
 *
 * A static object returned from the mock would have made every interaction
 * test a lie - the page commits a selection with `history.pushState` plus a
 * `popstate` event (see the page's `commit`), so a mock that ignores both
 * would leave the selection frozen while the assertions passed against
 * whatever was set up by hand. With this, clicking a basis really does drive
 * the URL, which really does drive the refetch. */
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

/** Puts the page's starting URL in place, the way a shared link would. */
function startAt(query: string) {
  window.history.replaceState(null, "", `/analytics${query ? `?${query}` : ""}`);
}

const { fetchMarketBases, fetchMarketFilters, fetchMarketOverview } = vi.hoisted(() => ({
  fetchMarketBases: vi.fn(),
  fetchMarketFilters: vi.fn(),
  fetchMarketOverview: vi.fn(),
}));
vi.mock("@/lib/marketAnalytics", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/marketAnalytics")>("@/lib/marketAnalytics");
  return { ...actual, fetchMarketBases, fetchMarketFilters, fetchMarketOverview };
});

/** The Card Pirate Index hero is exercised in indexHero.test.tsx; here it only
 * has to stay out of the way of the coverage-statistics assertions - and be
 * mocked at all, because the page fetches it on mount and an unmocked module
 * would reach the network from jsdom. */
const { fetchIndexDefault, fetchIndexSeries } = vi.hoisted(() => ({
  fetchIndexDefault: vi.fn(),
  fetchIndexSeries: vi.fn(),
}));
vi.mock("@/lib/cardPirateIndex", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/cardPirateIndex")>("@/lib/cardPirateIndex");
  return { ...actual, fetchIndexDefault, fetchIndexSeries };
});

import type {
  MarketBasis,
  MarketBucket,
  MarketOverview,
} from "@/lib/marketAnalytics";

import MarketLandscapePage from "./page";

// --- fixtures ---------------------------------------------------------------

const BASES: MarketBasis[] = [
  {
    key: "market_index",
    kind: "market_index",
    source: null,
    reference_type: null,
    evidence_type: null,
    available: true,
    unavailable_reason: null,
    usable_priced_prints: 296,
  },
  {
    key: "source:snkrdunk",
    kind: "source",
    source: "snkrdunk",
    reference_type: "listing_floor",
    evidence_type: "listing",
    available: true,
    unavailable_reason: null,
    usable_priced_prints: 25,
  },
  {
    key: "source:yuyutei",
    kind: "source",
    source: "yuyutei",
    reference_type: "retail_sell",
    evidence_type: "listing",
    available: true,
    unavailable_reason: null,
    usable_priced_prints: 279,
  },
];

const FILTERS = {
  sets: [
    { value: "EB-01", label: "EB-01" },
    { value: "OP-01", label: "OP-01" },
  ],
  rarities: [
    { value: "C", label: "C" },
    { value: "SP CARD", label: "SP CARD" },
  ],
};

/** The server's fixed bands. Written out rather than generated so a test that
 * asserts on a band is asserting on the same literal a reader sees. */
function buckets(counts: number[]): MarketBucket[] {
  const bands: [number, number | null, string][] = [
    [0, 99, "Under ¥100"],
    [100, 299, "¥100–299"],
    [300, 999, "¥300–999"],
    [1000, 2999, "¥1,000–2,999"],
    [3000, 9999, "¥3,000–9,999"],
    [10000, 29999, "¥10,000–29,999"],
    [30000, 99999, "¥30,000–99,999"],
    [100000, null, "¥100,000+"],
  ];
  return bands.map(([lower, upper, label], i) => ({
    lower_jpy: lower,
    upper_jpy: upper,
    label,
    count: counts[i] ?? 0,
  }));
}

function overview(partial: Partial<MarketOverview> = {}): MarketOverview {
  return {
    price_basis: "market_index",
    kind: "market_index",
    source: null,
    reference_type: null,
    evidence_type: null,
    available: true,
    unavailable_reason: null,
    scope: { active_prints: 4316, set: null, rarity: null },
    coverage: {
      observed_prints: null,
      usable_priced_prints: 296,
      coverage_pct: 6.86,
      excluded_constrained_prints: null,
      unavailable_prints: 4020,
    },
    current_price: {
      constituent_count: 296,
      median_jpy: 80,
      p10_jpy: 30,
      p90_jpy: 220,
      unavailable_reason: null,
    },
    distribution: buckets([225, 43, 4, 10, 9, 4, 1, 0]),
    index_composition: { single_source_prints: 288, multi_source_prints: 8 },
    ...partial,
  };
}

/** Staging's SNKRDUNK: 43 prints carry a number, 18 of them are the platform
 * minimum, and only 25 are prices. */
function snkrdunkOverview(partial: Partial<MarketOverview> = {}): MarketOverview {
  return overview({
    price_basis: "source:snkrdunk",
    kind: "source",
    source: "snkrdunk",
    reference_type: "listing_floor",
    evidence_type: "listing",
    coverage: {
      observed_prints: 43,
      usable_priced_prints: 25,
      coverage_pct: 0.58,
      excluded_constrained_prints: 18,
      unavailable_prints: 4291,
    },
    current_price: {
      constituent_count: 25,
      median_jpy: 3300,
      p10_jpy: 1500,
      p90_jpy: 19400,
      unavailable_reason: null,
    },
    distribution: buckets([0, 0, 0, 11, 9, 4, 1, 0]),
    index_composition: null,
    ...partial,
  });
}

/** Staging's real five-day series, so the hero on this page renders the same
 * numbers a reader would actually see. Its own behaviour is asserted in
 * indexHero.test.tsx. */
const INDEX_SERIES = {
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
  points: [
    {
      date: "2026-09-03", value: "1000.0000", is_base: true, prior_point_date: null,
      step_days: null, chain_link_log_return: null, constituent_count: 0,
      eligible_print_count: 231, movers_up: null, movers_down: null,
      movers_flat: null, capped_count: null,
    },
    {
      date: "2026-09-07", value: "1000.1065", is_base: false,
      prior_point_date: "2026-09-06", step_days: 1,
      chain_link_log_return: "-0.000850790688", constituent_count: 296,
      eligible_print_count: 305, movers_up: 1, movers_down: 3, movers_flat: 292,
      capped_count: 2,
    },
  ],
  starting_value: "1000.0000",
  current_value: "1000.1065",
  low_value: "1000.0000",
  high_value: "1000.9577",
  change: {
    absolute: "0.1065", pct: "0.010650", from_date: "2026-09-03",
    to_date: "2026-09-07", spans_break: false,
  },
  change_unavailable_reason: null,
  windows: [
    { token: "2w", available: false, covered_days: 5, required_days: 14 },
    { token: "1m", available: false, covered_days: 5, required_days: 30 },
    { token: "3m", available: false, covered_days: 5, required_days: 90 },
    { token: "6m", available: false, covered_days: 5, required_days: 180 },
    { token: "1y", available: false, covered_days: 5, required_days: 365 },
    { token: "2y", available: false, covered_days: 5, required_days: 730 },
    { token: "all", available: true, covered_days: 5, required_days: null },
  ],
  default_window: "all",
  breaks: [],
};

beforeEach(() => {
  startAt("");
  fetchMarketBases.mockResolvedValue({ bases: BASES });
  fetchMarketFilters.mockResolvedValue(FILTERS);
  fetchMarketOverview.mockResolvedValue(overview());
  fetchIndexDefault.mockResolvedValue(INDEX_SERIES);
  fetchIndexSeries.mockResolvedValue(INDEX_SERIES);
});

afterEach(() => {
  vi.clearAllMocks();
});

/** Renders and waits for the page to REACH A SETTLED STATE - both fetches
 * resolved (or rejected) and the loading block gone.
 *
 * Waiting only for the controls to appear is not enough and was silently wrong
 * at first: the vocabulary resolves one tick before the overview, so a test
 * that continued there asserted against a page still showing its spinner. */
async function renderPage() {
  render(<MarketLandscapePage />);
  await waitFor(() => expect(screen.queryByText("Loading catalogue prices…")).toBeNull());
}

// --- A. controls come from the server ---------------------------------------

describe("the price basis control is built from /analytics/market/bases", () => {
  it("offers one option per basis the server returned, and no others", async () => {
    await renderPage();
    const group = screen.getByRole("group", { name: /price basis/i });
    const labels = within(group)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels).toEqual([
      "Market Index",
      "SNKRDUNK · Current listing",
      "Yuyu-Tei · Retail price",
    ]);
  });

  it("renders a platform this build has never heard of, generically", async () => {
    // The genericity property that actually matters: a source added
    // server-side must appear with no frontend release. Nothing is registered
    // for "cardrush" in sourceDisplayName, and nothing for "auction_high" in
    // sourceEvidence - so the name passes through and the instrument is
    // humanised from the server's own token.
    fetchMarketBases.mockResolvedValue({
      bases: [
        ...BASES,
        {
          key: "source:cardrush",
          kind: "source",
          source: "cardrush",
          reference_type: "auction_high",
          evidence_type: "transaction",
          available: true,
          unavailable_reason: null,
          usable_priced_prints: 12,
        } as MarketBasis,
      ],
    });
    await renderPage();
    expect(screen.getByRole("button", { name: "cardrush · Auction high" })).toBeTruthy();
  });

  it("offers no basis at all when the server returns none", async () => {
    // No hardcoded fallback list anywhere - an empty response means an empty
    // control, not a plausible guess.
    fetchMarketBases.mockResolvedValue({ bases: [] });
    render(<MarketLandscapePage />);
    await waitFor(() => expect(fetchMarketOverview).toHaveBeenCalled());
    const group = screen.getByRole("group", { name: /price basis/i });
    expect(within(group).queryAllByRole("button")).toHaveLength(0);
  });

  it("selects Market Index by default", async () => {
    await renderPage();
    expect(screen.getByRole("button", { name: "Market Index" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(fetchMarketOverview).toHaveBeenCalledWith(
      expect.objectContaining({ priceBasis: "market_index" }),
    );
  });
});

describe("the scope controls are built from /analytics/market/filters", () => {
  it("offers exactly the sets and rarities the server published", async () => {
    await renderPage();
    const setOptions = within(screen.getByLabelText("Set"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(setOptions).toEqual(["All sets", "EB-01", "OP-01"]);

    const rarityOptions = within(screen.getByLabelText("Rarity or special print"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(rarityOptions).toEqual(["All rarities", "C", "SP CARD"]);
  });

  it("uses the server's value verbatim, never a transformed identifier", async () => {
    // The `OP01` vs `OP-01` trap: the wire value is the option value, with no
    // client-side reshaping between the dropdown and the request.
    await renderPage();
    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "OP-01" } });
    await waitFor(() =>
      expect(fetchMarketOverview).toHaveBeenLastCalledWith(
        expect.objectContaining({ set: "OP-01" }),
      ),
    );
  });

  it("disables a scope control the server published nothing for", async () => {
    fetchMarketFilters.mockResolvedValue({ sets: [], rarities: FILTERS.rarities });
    await renderPage();
    const select = screen.getByLabelText("Set") as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "No set options",
    ]);
  });
});

// --- B. filters drive the request -------------------------------------------

describe("changing a control re-requests the overview", () => {
  it("re-fetches when the price basis changes", async () => {
    await renderPage();
    fetchMarketOverview.mockResolvedValue(snkrdunkOverview());

    fireEvent.click(screen.getByRole("button", { name: "SNKRDUNK · Current listing" }));

    await waitFor(() =>
      expect(fetchMarketOverview).toHaveBeenLastCalledWith(
        expect.objectContaining({ priceBasis: "source:snkrdunk" }),
      ),
    );
  });

  it("re-fetches when the set filter changes", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "EB-01" } });
    await waitFor(() =>
      expect(fetchMarketOverview).toHaveBeenLastCalledWith(
        expect.objectContaining({ set: "EB-01" }),
      ),
    );
  });

  it("re-fetches when the rarity filter changes", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Rarity or special print"), {
      target: { value: "SP CARD" },
    });
    await waitFor(() =>
      expect(fetchMarketOverview).toHaveBeenLastCalledWith(
        expect.objectContaining({ rarity: "SP CARD" }),
      ),
    );
  });

  it("reads its initial selection out of the URL", async () => {
    startAt("basis=source:yuyutei&set=OP-01&rarity=C");
    await renderPage();
    expect(fetchMarketOverview).toHaveBeenCalledWith({
      priceBasis: "source:yuyutei",
      set: "OP-01",
      rarity: "C",
    });
  });

  it("falls back to the default rather than requesting a value the server never offered", async () => {
    // A stale bookmark naming a retired platform, or a set that no longer has
    // active prints. Validated against the SERVER's list - this build has no
    // opinion of its own about which platforms exist.
    startAt("basis=source:retired&set=ZZ-99&rarity=NOPE");
    await renderPage();
    expect(fetchMarketOverview).toHaveBeenCalledWith({
      priceBasis: "market_index",
      set: undefined,
      rarity: undefined,
    });
  });

  it("never sends a window parameter", async () => {
    // The endpoint has none, by design (this tranche reports what prices ARE).
    // A client that invented one would be asking for an answer the archive
    // cannot give.
    startAt("window=30d");
    await renderPage();
    const call = fetchMarketOverview.mock.calls[0][0];
    expect(Object.keys(call)).toEqual(["priceBasis", "set", "rarity"]);
  });
});

// --- C. null is never zero --------------------------------------------------

describe("a statistic with no answer reads Unavailable, never a number", () => {
  it("renders Unavailable for a null median and a null price band", async () => {
    fetchMarketOverview.mockResolvedValue(
      overview({
        coverage: {
          observed_prints: null,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: null,
          unavailable_prints: 105,
        },
        scope: { active_prints: 105, set: "EB-02", rarity: null },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
        index_composition: { single_source_prints: 0, multi_source_prints: 0 },
      }),
    );
    await renderPage();

    const median = screen.getByText("Median price").closest("div")!.parentElement!;
    expect(within(median).getByText("Unavailable")).toBeTruthy();
    // The specific failure this guards: ¥0 is a price, and rendering one here
    // would state that the median IS zero yen.
    expect(median.textContent).not.toMatch(/[¥￥]\s*0\b/);
  });

  it("renders Unavailable for deciles the server withheld, while keeping the median it gave", async () => {
    // n=4: a median over four points is a defensible statement, a 10th
    // percentile over four points is arithmetic on noise. The server draws
    // that line; the page must not paper over it.
    fetchMarketOverview.mockResolvedValue(
      snkrdunkOverview({
        coverage: {
          observed_prints: 5,
          usable_priced_prints: 4,
          coverage_pct: 2.6,
          excluded_constrained_prints: 1,
          unavailable_prints: 150,
        },
        current_price: {
          constituent_count: 4,
          median_jpy: 7750,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "insufficient_constituents",
        },
      }),
    );
    await renderPage();

    expect(screen.getByText("￥7,750")).toBeTruthy();
    const band = screen.getByText("Price band").closest("div")!.parentElement!;
    expect(within(band).getByText("Unavailable")).toBeTruthy();
    expect(band.textContent).toContain("too few priced prints to describe a spread");
  });

  it("shows no coverage percentage at all for an empty scope", async () => {
    // 0/0 is not 0%. The whole body is replaced rather than rendering four
    // zeros against a denominator that does not exist.
    fetchMarketOverview.mockResolvedValue(
      overview({
        scope: { active_prints: 0, set: "OP-01", rarity: "TR" },
        coverage: {
          observed_prints: null,
          usable_priced_prints: 0,
          coverage_pct: null,
          excluded_constrained_prints: null,
          unavailable_prints: 0,
        },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
        index_composition: { single_source_prints: 0, multi_source_prints: 0 },
      }),
    );
    await renderPage();

    expect(screen.getByText("No active prints match this scope.")).toBeTruthy();
    expect(screen.queryByText("Catalogue coverage")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\b0(\.0)?%/);
  });

  it("still shows a genuine 0% when the scope really does hold prints", async () => {
    // The other half of the rule, and the reason the one above is about
    // NULL rather than about zero: 0 of 105 priced IS 0%, and hiding it would
    // be its own dishonesty.
    fetchMarketOverview.mockResolvedValue(
      overview({
        scope: { active_prints: 105, set: "EB-02", rarity: null },
        coverage: {
          observed_prints: null,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: null,
          unavailable_prints: 105,
        },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
        index_composition: { single_source_prints: 0, multi_source_prints: 0 },
      }),
    );
    await renderPage();
    const coverage = screen.getByText("Catalogue coverage").closest("div")!.parentElement!;
    expect(coverage.textContent).toContain("0%");
    expect(coverage.textContent).toContain("105");
  });
});

// --- D. the distribution ----------------------------------------------------

describe("price distribution", () => {
  it("renders every band the server sent, with the server's own label and count", async () => {
    await renderPage();
    const section = screen.getByText("Price distribution").closest("section")!;
    for (const [label, count] of [
      ["Under ¥100", "225"],
      ["¥100–299", "43"],
      ["¥300–999", "4"],
      ["¥1,000–2,999", "10"],
      ["¥3,000–9,999", "9"],
      ["¥10,000–29,999", "4"],
      ["¥30,000–99,999", "1"],
      ["¥100,000+", "0"],
    ] as const) {
      const row = within(section).getByText(label).closest("li")!;
      expect(row.textContent).toContain(count);
    }
  });

  it("keeps empty bands visible rather than dropping them", async () => {
    // An absent ¥100,000+ row and an empty one mean different things: "no card
    // is priced that high" versus "this chart does not go that high".
    await renderPage();
    const section = screen.getByText("Price distribution").closest("section")!;
    expect(within(section).getAllByRole("listitem")).toHaveLength(8);
  });

  it("renders no percentages, because the API publishes none", async () => {
    await renderPage();
    const section = screen.getByText("Price distribution").closest("section")!;
    expect(section.textContent).not.toMatch(/%/);
  });

  it("says so plainly when nothing in scope is priced", async () => {
    fetchMarketOverview.mockResolvedValue(
      overview({
        coverage: {
          observed_prints: null,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: null,
          unavailable_prints: 105,
        },
        scope: { active_prints: 105, set: "EB-02", rarity: null },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
      }),
    );
    await renderPage();
    expect(
      screen.getByText(/Nothing in this scope is priced yet, so there is no distribution/i),
    ).toBeTruthy();
  });

  it("updates when the basis changes", async () => {
    await renderPage();
    let section = screen.getByText("Price distribution").closest("section")!;
    expect(within(section).getByText("Under ¥100").closest("li")!.textContent).toContain("225");

    fetchMarketOverview.mockResolvedValue(snkrdunkOverview());
    fireEvent.click(screen.getByRole("button", { name: "SNKRDUNK · Current listing" }));

    await waitFor(() => {
      section = screen.getByText("Price distribution").closest("section")!;
      expect(within(section).getByText("Under ¥100").closest("li")!.textContent).toContain("0");
    });
    expect(within(section).getByText("¥1,000–2,999").closest("li")!.textContent).toContain("11");
  });
});

// --- E. coverage and composition --------------------------------------------

describe("the page states the index's composition exactly once", () => {
  it("no longer carries a source-count section calling itself the index's makeup", async () => {
    // TASK INDEX 2B-C2. This block used to render "What the index is made of"
    // - the live-resolver split of priced prints by SOURCE COUNT. It was
    // accurate, and it was removed because /analytics now opens with an Index
    // Composition panel of nearly the same name answering a different
    // question, and the two printed overlapping numbers from unrelated
    // populations.
    await renderPage();
    expect(screen.queryByText("What the index is made of")).toBeNull();
    expect(screen.queryByText("Two or more sources")).toBeNull();
    expect(screen.queryByText("One source")).toBeNull();
    // The removed bar's own total label. Asserted as the exact string rather
    // than the loose phrase: "priced prints in this view" also appears in the
    // Price distribution caption, which is unrelated and stays.
    expect(document.body.textContent).not.toContain("296 priced prints in this view");
  });

  it("keeps every other market-overview section it did not own", async () => {
    // The overview response has four other consumers on this page, so the
    // request stays and so do they. Removing the section is not removing the
    // basis.
    await renderPage();
    expect(screen.getByText("Priced prints")).toBeTruthy();
    expect(screen.getByText("Catalogue coverage")).toBeTruthy();
    expect(screen.getByText("Price distribution")).toBeTruthy();
    expect(screen.getByText("Browse the card catalogue →")).toBeTruthy();
  });
});

describe("a source's observed, usable and excluded counts stay three different numbers", () => {
  beforeEach(() => {
    fetchMarketOverview.mockResolvedValue(snkrdunkOverview());
    startAt("basis=source:snkrdunk");
  });

  it("shows all three, and does not present the observed count as priced", async () => {
    await renderPage();

    const priced = screen.getByText("Priced prints").closest("div")!.parentElement!;
    expect(within(priced).getByText("25")).toBeTruthy();
    expect(priced.textContent).toContain("43 observed on this source");

    const section = screen.getByText("What this source reports").closest("section")!;
    expect(within(section).getByText("Usable prices").closest("li")!.textContent).toContain("25");
    expect(
      within(section).getByText("Excluded by source constraints").closest("li")!.textContent,
    ).toContain("18");
    expect(section.textContent).toContain("43 prints observed on this source");
  });

  it("keeps the constrained count out of every price statistic", async () => {
    // The ¥1,000 platform minimum must never look like a market price. The
    // median, the band and the lowest occupied band are all above it, and the
    // page states in words that the excluded readings enter none of them.
    await renderPage();
    expect(screen.getByText("￥3,300")).toBeTruthy();
    expect(screen.getByText("￥1,500 – ￥19,400")).toBeTruthy();

    const distribution = screen.getByText("Price distribution").closest("section")!;
    for (const emptyBand of ["Under ¥100", "¥100–299", "¥300–999"]) {
      expect(within(distribution).getByText(emptyBand).closest("li")!.textContent).toContain("0");
    }

    const section = screen.getByText("What this source reports").closest("section")!;
    expect(section.textContent).toMatch(
      /never enters the median, the price band or the distribution/i,
    );
  });

  it("does not imply the excluded prints are untracked or unlisted", async () => {
    await renderPage();
    const section = screen.getByText("What this source reports").closest("section")!;
    expect(section.textContent).toMatch(/tracked and observed on this source/i);
    expect(section.textContent).not.toMatch(/no listing|not listed|unlisted|no history/i);
  });

  it("shows no excluded-constraint explanation when nothing is excluded", async () => {
    // Yuyu-Tei: 279 observed, 279 usable, 0 excluded - and its 37 sale-priced
    // prints are eligible, so none of them is impaired coverage. A page that
    // read `constraint` as a synonym for "excluded" would have shown those 37
    // as a problem.
    fetchMarketOverview.mockResolvedValue(
      snkrdunkOverview({
        price_basis: "source:yuyutei",
        source: "yuyutei",
        reference_type: "retail_sell",
        coverage: {
          observed_prints: 279,
          usable_priced_prints: 279,
          coverage_pct: 6.46,
          excluded_constrained_prints: 0,
          unavailable_prints: 4037,
        },
      }),
    );
    startAt("basis=source:yuyutei");
    await renderPage();

    const section = screen.getByText("What this source reports").closest("section")!;
    expect(section.textContent).toContain("279");
    expect(section.textContent).not.toMatch(/never enters the median/i);
    // The supporting "N observed" line is suppressed too - observed equals
    // usable, so there is nothing to explain.
    const priced = screen.getByText("Priced prints").closest("div")!.parentElement!;
    expect(priced.textContent).not.toMatch(/observed/i);
  });
});

// --- F. movement ------------------------------------------------------------

describe("the page is not a dead end", () => {
  it("offers a way into the card catalogue", async () => {
    await renderPage();
    const link = screen.getByRole("link", { name: /browse the card catalogue/i });
    expect(link.getAttribute("href")).toBe("/cards");
  });

  it("carries rarity into the catalogue, because /prints actually filters on it", async () => {
    fetchMarketOverview.mockResolvedValue(
      overview({ scope: { active_prints: 307, set: null, rarity: "L" } }),
    );
    startAt("rarity=L");
    await renderPage();
    const link = screen.getByRole("link", { name: /browse L cards in the catalogue/i });
    expect(link.getAttribute("href")).toBe("/cards?rarity=L");
  });

  it("never carries a set, because /prints has no set parameter to honour it", async () => {
    // Passing ?set= would put a parameter in the URL that /cards silently
    // ignores, landing the collector on the whole catalogue while believing
    // they were looking at one set. The label must not claim it either.
    fetchMarketOverview.mockResolvedValue(
      overview({ scope: { active_prints: 154, set: "OP-01", rarity: null } }),
    );
    startAt("set=OP-01");
    await renderPage();
    const link = screen.getByRole("link", { name: /browse the card catalogue/i });
    expect(link.getAttribute("href")).toBe("/cards");
    expect(link.getAttribute("href")).not.toContain("set=");
    expect(link.textContent).not.toMatch(/OP-01|these cards/i);
  });
});

describe("the page no longer says movement cannot be answered", () => {
  /** The section this replaces existed for one reason: to state that the
   * archive could not compare a card against its own past. The Card Pirate
   * Index compares the whole priced catalogue against its own past, and it is
   * now the first thing on the page. Leaving the old paragraph below it would
   * have put a flat denial directly under the chart that refutes it. */
  it("the 'not enough history' section is gone", async () => {
    await renderPage();
    expect(screen.queryByText("Price movement")).toBeNull();
    expect(screen.queryByText("Not enough comparable price history yet.")).toBeNull();
  });

  it("still shows no movers, gainers, losers or rankings", async () => {
    await renderPage();
    expect(document.body.textContent).not.toMatch(
      /gainer|loser|top movers|trending|sentiment|market cap/i,
    );
  });

  it("offers no window control the index API does not publish", async () => {
    await renderPage();
    // The print page's 7D/30D grammar is NOT this endpoint's; offering one
    // here would send a token the index API answers with a 400.
    for (const label of ["24H", "7D", "30D", "90D", "5Y"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
  });
});

describe("refreshing does not collapse the page", () => {
  it("keeps the previous view on screen, marked busy, while a new basis loads", async () => {
    // The defect this pins: swapping the body for a loading box on every
    // control change collapsed ~1000px of content and snapped it back, a
    // visible layout shift on the interaction a collector repeats most.
    await renderPage();
    expect(screen.getByText("Priced prints")).toBeTruthy();

    let release: (value: MarketOverview) => void = () => {};
    fetchMarketOverview.mockReturnValue(
      new Promise<MarketOverview>((resolve) => {
        release = resolve;
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "SNKRDUNK · Current listing" }));

    // Still rendered, and still the OLD numbers - not a spinner, not zeroes.
    //
    // SCOPED TO THE LANDSCAPE'S OWN BUSY REGION. A bare document-wide query
    // used to be unambiguous because this was the page's only `aria-busy`
    // element; the index hero's skeleton and the composition panel's are both
    // legitimately busy too, so the query has to name which region it means or
    // it silently starts asserting about a different one.
    // On a REFRESH the landscape keeps its content, so it is identified by
    // the stat it is still showing rather than by a loading caption it does
    // not have.
    const landscapeBusy = () =>
      [...document.querySelectorAll("[aria-busy='true']")].find((el) =>
        el.contains(screen.getByText("Priced prints")),
      );
    await waitFor(() => expect(landscapeBusy()).toBeTruthy());
    expect(screen.getByText("Priced prints")).toBeTruthy();
    // The STAT TILE's 296, not any 296 on the page - the breadth panel prints the
    // same constituent count, so a bare text query is ambiguous. Same scoping
    // the SNKRDUNK assertion below already uses for exactly this reason.
    const pricedTile = () =>
      screen.getByText("Priced prints").closest("div")!.parentElement!;
    expect(within(pricedTile()).getByText("296")).toBeTruthy();
    expect(screen.queryByText("Loading catalogue prices…")).toBeNull();

    release(snkrdunkOverview());
    // "25" appears twice once SNKRDUNK loads (the stat and the legend), so
    // this asserts on the stat tile specifically rather than on the string.
    await waitFor(() => {
      const priced = screen.getByText("Priced prints").closest("div")!.parentElement!;
      expect(within(priced).getByText("25")).toBeTruthy();
    });
    expect(landscapeBusy()).toBeUndefined();
  });

  it("shows a page-shaped placeholder on first paint, not a small box", async () => {
    fetchMarketOverview.mockReturnValue(new Promise<MarketOverview>(() => {}));
    render(<MarketLandscapePage />);
    await waitFor(() => expect(screen.getByText("Loading catalogue prices…")).toBeTruthy());
    // The LANDSCAPE's placeholder specifically - the index hero and the
    // composition panel have busy skeletons of their own, so a document-wide
    // `[aria-busy]` query would now pick up whichever renders first.
    const busy = screen
      .getByText("Loading catalogue prices…")
      .closest("[aria-busy='true']")!;
    // Four stat placeholders and a chart-sized block, so the first frame is
    // roughly the height the real content will be.
    expect(busy.querySelectorAll(".panel")).toHaveLength(5);
  });
});

describe("a section with nothing to say is omitted, not padded with zeroes", () => {
  it("drops the index composition when nothing in scope is priced", async () => {
    fetchMarketOverview.mockResolvedValue(
      overview({
        scope: { active_prints: 105, set: "EB-02", rarity: null },
        coverage: {
          observed_prints: null,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: null,
          unavailable_prints: 105,
        },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
        index_composition: { single_source_prints: 0, multi_source_prints: 0 },
      }),
    );
    await renderPage();
    // The section is gone for every Market Index view now, not only for an
    // empty one - see "the page states the index's composition exactly once".
    expect(screen.queryByText("What the index is made of")).toBeNull();
    // The stats themselves still report the real zero.
    expect(screen.getByText("Catalogue coverage")).toBeTruthy();
  });

  it("drops the source breakdown when the source observed nothing in scope", async () => {
    fetchMarketOverview.mockResolvedValue(
      snkrdunkOverview({
        available: false,
        unavailable_reason: "no_usable_prices_in_scope",
        scope: { active_prints: 17, set: "ST-01", rarity: null },
        coverage: {
          observed_prints: 0,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: 0,
          unavailable_prints: 17,
        },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
      }),
    );
    startAt("basis=source:snkrdunk&set=ST-01");
    await renderPage();
    expect(screen.queryByText("What this source reports")).toBeNull();
    // The explicit "genuinely zero, not missing" note still carries the answer.
    expect(screen.getByText(/genuinely zero for this view/i)).toBeTruthy();
  });
});

// --- G. failure and loading -------------------------------------------------

describe("failure states", () => {
  it("reports a failed vocabulary fetch without inventing controls", async () => {
    fetchMarketBases.mockRejectedValue(new Error("boom"));
    render(<MarketLandscapePage />);
    await waitFor(() =>
      expect(screen.getByText(/catalogue prices could not be loaded/i)).toBeTruthy(),
    );
    expect(screen.queryByRole("group", { name: /price basis/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/[¥￥]\s*0\b/);
  });

  it("keeps the controls usable when only the overview fails", async () => {
    fetchMarketOverview.mockRejectedValue(new Error("boom"));
    await renderPage();
    expect(screen.getByText(/this view of the market could not be loaded/i)).toBeTruthy();
    // The filters survive, so the visitor can change scope and try again
    // rather than being left on a dead page.
    expect(screen.getByRole("button", { name: "Market Index" })).toBeTruthy();
    expect(screen.queryByText("Priced prints")).toBeNull();
  });

  it("shows an explicitly unavailable basis without hiding its real zeros", async () => {
    fetchMarketOverview.mockResolvedValue(
      snkrdunkOverview({
        available: false,
        unavailable_reason: "no_usable_prices_in_scope",
        scope: { active_prints: 17, set: "ST-01", rarity: null },
        coverage: {
          observed_prints: 0,
          usable_priced_prints: 0,
          coverage_pct: 0,
          excluded_constrained_prints: 0,
          unavailable_prints: 17,
        },
        current_price: {
          constituent_count: 0,
          median_jpy: null,
          p10_jpy: null,
          p90_jpy: null,
          unavailable_reason: "no_usable_prices",
        },
        distribution: buckets([]),
      }),
    );
    startAt("basis=source:snkrdunk&set=ST-01");
    await renderPage();
    expect(screen.getByText(/no usable prices in the current scope/i)).toBeTruthy();
    expect(screen.getByText(/genuinely zero for this view/i)).toBeTruthy();
  });
});

// --- H. structure -----------------------------------------------------------

describe("control structure is mobile-safe and accessible", () => {
  it("names every control for a screen reader, and groups the basis buttons", async () => {
    await renderPage();
    // The visible "Set"/"Rarity" captions are hidden below `sm`, so the
    // accessible name has to carry them at every width.
    expect(screen.getByLabelText("Set")).toBeTruthy();
    expect(screen.getByLabelText("Rarity or special print")).toBeTruthy();
    expect(screen.getByRole("group", { name: /price basis/i })).toBeTruthy();
    for (const button of within(
      screen.getByRole("group", { name: /price basis/i }),
    ).getAllByRole("button")) {
      expect(button.getAttribute("aria-pressed")).toMatch(/true|false/);
    }
  });

  it("wraps its control rows rather than forcing a horizontal scroll", async () => {
    await renderPage();
    const group = screen.getByRole("group", { name: /price basis/i });
    expect(group.querySelector(".flex-wrap")).toBeTruthy();
    const scope = screen.getByLabelText("Set").closest("div.flex")!;
    expect(scope.className).toContain("flex-wrap");
  });

  it("gives the numeric bars no accessible presence of their own", async () => {
    // The bar is decoration over a number that is already text; announcing it
    // twice would make the chart read as gibberish.
    await renderPage();
    const section = screen.getByText("Price distribution").closest("section")!;
    for (const bar of section.querySelectorAll("span[style]")) {
      expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  });
});

describe("the page reads as a landscape, not a terminal", () => {
  it("uses no gain/loss colour vocabulary", async () => {
    fetchMarketOverview.mockResolvedValue(snkrdunkOverview());
    await renderPage();
    const html = document.body.innerHTML;
    expect(html).not.toMatch(/price-positive|price-negative|signal-red|signal-green/);
  });

  it("describes the selected basis in the collector's words", async () => {
    fetchMarketOverview.mockResolvedValue(snkrdunkOverview());
    startAt("basis=source:snkrdunk");
    await renderPage();
    expect(screen.getByText(/Using SNKRDUNK · Current listing/)).toBeTruthy();
  });
});
