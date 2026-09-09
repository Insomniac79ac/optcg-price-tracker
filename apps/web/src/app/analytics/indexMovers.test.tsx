/** The "What moved the Index?" section on /analytics.
 *
 * WHAT THIS SUITE IS FOR. The section restates a payload the server already
 * computed, and the failure mode worth guarding is not "the layout broke" but
 * "the client started producing figures of its own" - a re-sort, a recomputed
 * percentage, a merged price/impact number, or a request the timeframe control
 * can reach. Hence the emphasis on request counts, on rendering the exact
 * strings the API sent, and on the two columns staying separate.
 *
 * The fixtures are staging's REAL archived payloads for 2026-09-07 (four
 * movers, two capped, one up and three down) and 2026-09-06 (a quiet day),
 * so a test that passes here is describing data the product has actually
 * served.
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
import type {
  IndexComposition,
  IndexMover,
  IndexMovers,
  IndexPoint,
  IndexSeries,
  IndexWindowRow,
} from "@/lib/cardPirateIndex";

const WINDOWS: IndexWindowRow[] = [
  { token: "2w", available: true, covered_days: 5, required_days: 14 },
  { token: "1m", available: true, covered_days: 5, required_days: 30 },
  { token: "3m", available: true, covered_days: 5, required_days: 90 },
  { token: "6m", available: true, covered_days: 5, required_days: 180 },
  { token: "1y", available: true, covered_days: 5, required_days: 365 },
  { token: "2y", available: true, covered_days: 5, required_days: 730 },
  { token: "all", available: true, covered_days: 5, required_days: null },
];

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

function composition(): IndexComposition {
  return {
    as_of: "2026-09-07",
    constituent_count: 296,
    rarity: [
      { key: "C", label: "C", count: 134, pct: 45.27 },
      { key: "R", label: "R", count: 70, pct: 23.65 },
    ],
  };
}

const BANDAI = "https://www.onepiece-cardgame.com/images/cardlist/card";

/** Staging's real 2026-09-07 movers, verbatim from
 * GET /analytics/index/movers?date=2026-09-07. */
const LAW: IndexMover = {
  card_print_id: 5686,
  card_code: "OP01-047",
  name: "Trafalgar Law",
  rarity: "SP CARD",
  display_image_url: `${BANDAI}/OP01-047_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 17000,
  current_value_jpy: 10000,
  direction: "down",
  raw_pct: -41.18,
  capped_log_return: "-0.223143551314209756",
  was_capped: true,
  contribution_log_return: "-0.000753863349034492",
  approx_index_points: "-0.7546",
  move_rank: 1,
  impact_rank: 1,
};

const ST_NAMI: IndexMover = {
  card_print_id: 6796,
  card_code: "ST01-007",
  name: "Nami",
  rarity: "C",
  display_image_url: `${BANDAI}/ST01-007_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 2000,
  current_value_jpy: 1500,
  direction: "down",
  raw_pct: -25.0,
  capped_log_return: "-0.223143551314209756",
  was_capped: true,
  contribution_log_return: "-0.000753863349034492",
  approx_index_points: "-0.7546",
  move_rank: 2,
  impact_rank: 2,
};

const OP_NAMI: IndexMover = {
  card_print_id: 6807,
  card_code: "OP01-016",
  name: "Nami",
  rarity: "R",
  display_image_url: `${BANDAI}/OP01-016_p1.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 3000,
  current_value_jpy: 3700,
  direction: "up",
  raw_pct: 23.33,
  capped_log_return: "0.209720530982069069",
  was_capped: false,
  contribution_log_return: "0.000708515307371855",
  approx_index_points: "0.7092",
  move_rank: 3,
  impact_rank: 3,
};

const HANCOCK: IndexMover = {
  card_print_id: 5687,
  card_code: "OP01-078",
  name: "Boa Hancock",
  rarity: "SP CARD",
  display_image_url: `${BANDAI}/OP01-078_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 66000,
  current_value_jpy: 65000,
  direction: "down",
  raw_pct: -1.52,
  capped_log_return: "-0.015267472130788434",
  was_capped: false,
  contribution_log_return: "-0.000051579297739150",
  approx_index_points: "-0.0516",
  move_rank: 4,
  impact_rank: 4,
};

function movers(partial: Partial<IndexMovers> = {}): IndexMovers {
  return {
    as_of: "2026-09-07",
    prior_point_date: "2026-09-06",
    constituent_count: 296,
    movers_count: 4,
    unchanged_count: 292,
    chain_link_log_return: "-0.000850790688",
    movers: [LAW, ST_NAMI, OP_NAMI, HANCOCK],
    truncated: false,
    ...partial,
  };
}

/** Staging's real 2026-09-06: 296 constituents, none of which moved. */
function quietDay(): IndexMovers {
  return {
    as_of: "2026-09-06",
    prior_point_date: "2026-09-05",
    constituent_count: 296,
    movers_count: 0,
    unchanged_count: 296,
    chain_link_log_return: "0E-12",
    movers: [],
    truncated: false,
  };
}

/** Staging's real 2026-09-03 base point. */
function basePoint(): IndexMovers {
  return {
    as_of: "2026-09-03",
    prior_point_date: null,
    constituent_count: 0,
    movers_count: 0,
    unchanged_count: 0,
    chain_link_log_return: null,
    movers: [],
    truncated: false,
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

function calls(path: string) {
  return apiGet.mock.calls.filter((c) => c[0] === path);
}

function stub({
  mov = movers(),
  movFails = false,
}: { mov?: unknown; movFails?: boolean } = {}) {
  apiGet.mockImplementation((path: string, opts?: { params?: { window?: string } }) => {
    if (path === "/analytics/index/movers") {
      return movFails ? Promise.reject(new Error("boom")) : Promise.resolve(mov);
    }
    if (path === "/analytics/index/composition") return Promise.resolve(composition());
    if (path === "/analytics/index") {
      const w = opts?.params?.window ?? "all";
      return Promise.resolve({ ...series(), requested_window: w, windows: WINDOWS });
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

/** Waits on the movers META line rather than on a row, so the empty-state and
 * base-point tests can share it. */
async function renderPage() {
  render(<MarketLandscapePage />);
  await waitFor(() => expect(screen.getByTestId("index-movers")).toBeTruthy());
  await waitFor(() =>
    expect(screen.queryByTestId("movers-list") || screen.queryByTestId("movers-none")
      || screen.queryByTestId("movers-base-point") || screen.queryByTestId("movers-unavailable"))
      .toBeTruthy(),
  );
}

function rows() {
  return screen.getAllByTestId("index-mover");
}

describe("normal rendering", () => {
  it("renders one row per mover, in the API's own order", async () => {
    await renderPage();
    const list = rows();
    expect(list).toHaveLength(4);
    // The API sends move_rank order; the client maps in place. Asserting the
    // ORDER is what makes an accidental `.sort()` a test failure.
    expect(list.map((r) => r.getAttribute("data-card-print-id"))).toEqual([
      "5686", "6796", "6807", "5687",
    ]);
  });

  it("heads the section with the movers API's own date and counts", async () => {
    await renderPage();
    expect(screen.getByTestId("movers-meta").textContent).toBe(
      "Sep 7, 2026 · 4 of 296 constituents moved",
    );
  });

  it("uses movers_count, not the number of rows it managed to render", async () => {
    // A truncated day is exactly where `movers.length` would lie: it reports
    // how many rows fitted, not how many constituents moved.
    stub({ mov: movers({ movers_count: 31, truncated: true, unchanged_count: 265 }) });
    await renderPage();
    expect(screen.getByTestId("movers-meta").textContent).toContain("31 of 296");
    expect(screen.getByTestId("movers-truncated").textContent).toContain(
      "Showing the 4 largest moves of 31",
    );
  });

  it("never surfaces move_rank or impact_rank as a numbered rank", async () => {
    await renderPage();
    for (const row of rows()) {
      expect(row.textContent).not.toMatch(/#\s*\d/);
    }
  });
});

describe("exact print identity", () => {
  it("keys and distinguishes rows by card_print_id, not card_code", async () => {
    await renderPage();
    // Two rows are both named "Nami" and are different prints. Identity has to
    // survive that: OP01-016 has seven prints in the catalogue.
    const namis = rows().filter((r) => r.textContent?.includes("Nami"));
    expect(namis).toHaveLength(2);
    expect(namis.map((r) => r.getAttribute("data-card-print-id"))).toEqual(["6796", "6807"]);
    expect(within(namis[0]).getByTestId("mover-card-code").textContent).toBe("ST01-007");
    expect(within(namis[1]).getByTestId("mover-card-code").textContent).toBe("OP01-016");
  });

  it("carries the name, code, rarity and language of each print", async () => {
    await renderPage();
    const law = rows()[0];
    expect(law.textContent).toContain("Trafalgar Law");
    expect(within(law).getByTestId("mover-card-code").textContent).toBe("OP01-047");
    // The shared RarityBadge renders the collector-facing term, so the raw
    // "SP CARD" token arrives on screen as "SP Card" - the point of reusing
    // the badge is that a rarity reads the same here as it does on /cards.
    expect(law.textContent).toContain("SP Card");
    expect(law.textContent?.toLowerCase()).toContain("jp");
  });
});

describe("artwork", () => {
  it("renders each mover's own display image through the same-origin rewrite", async () => {
    await renderPage();
    const images = rows().map((r) => within(r).getByRole("img") as HTMLImageElement);
    expect(images).toHaveLength(4);
    // Bandai's host sends Cross-Origin-Resource-Policy: same-site, so the
    // shared resolver routes it through /api/card-image. A raw Bandai src here
    // would render nothing but the placeholder in a real browser.
    expect(images[0].getAttribute("src")).toBe(
      `/api/card-image?u=${encodeURIComponent(`${BANDAI}/OP01-047_p2.png?260821`)}`,
    );
    expect(new Set(images.map((i) => i.getAttribute("src"))).size).toBe(4);
  });

  it("shows the whole card - contain, never cover, and 63:88 preserved", async () => {
    await renderPage();
    const img = within(rows()[0]).getByRole("img");
    expect(img.className).toContain("object-contain");
    expect(img.className).not.toContain("object-cover");
    // The frame, not the <img>, owns the ratio - so assert it on the frame.
    const frame = img.closest("div");
    expect(frame?.className).toContain("aspect-[63/88]");
  });
});

describe("price move is separate from index impact", () => {
  it("shows the archived prices and the card's own percentage", async () => {
    await renderPage();
    const move = within(rows()[0]).getByTestId("mover-price-move");
    expect(move.textContent).toContain("￥17,000");
    expect(move.textContent).toContain("￥10,000");
    expect(within(rows()[0]).getByTestId("mover-raw-pct").textContent).toBe("−41.18%");
  });

  it("shows the index impact as a separately labelled figure", async () => {
    await renderPage();
    const row = rows()[0];
    const impact = within(row).getByTestId("mover-index-impact");
    expect(impact.textContent).toContain("Index impact");
    expect(within(row).getByTestId("mover-index-points").textContent).toContain("−0.7546");
    // The two concepts are distinct elements, and neither contains the other.
    const move = within(row).getByTestId("mover-price-move");
    expect(move.contains(impact)).toBe(false);
    expect(impact.contains(move)).toBe(false);
    // The impact column must not restate the card's own percentage.
    expect(impact.textContent).not.toContain("41.18");
  });

  it("renders index points with an explicit sign in both directions", async () => {
    await renderPage();
    const pts = rows().map((r) => within(r).getByTestId("mover-index-points").textContent);
    expect(pts[0]).toContain("−0.7546");
    expect(pts[2]).toContain("+0.7092");
  });

  it("renders raw_pct as the server sent it, not derived from the cap", async () => {
    await renderPage();
    // ST01-007 fell exactly 25.00 % and was capped. If the client derived the
    // percentage from `capped_log_return` it would print −22.31 %.
    expect(within(rows()[1]).getByTestId("mover-raw-pct").textContent).toBe("−25.00%");
  });

  it("never describes the index impact as exact or additive", async () => {
    await renderPage();
    const panel = screen.getByTestId("index-movers");
    expect(panel.textContent).toContain("does not sum to");
    expect(panel.textContent).not.toMatch(/\bexact\b/i);
  });
});

describe("capping", () => {
  it("marks the capped movers and only those", async () => {
    await renderPage();
    const capped = rows().map((r) => within(r).queryByTestId("mover-capped") !== null);
    expect(capped).toEqual([true, true, false, false]);
  });

  it("explains the cap once, below the rows", async () => {
    await renderPage();
    expect(screen.getByTestId("movers-capped-note").textContent).toContain(
      "Large card moves are capped by the Index methodology, so price movement and Index impact may differ.",
    );
  });

  it("omits the explanation entirely on a day nothing was capped", async () => {
    stub({ mov: movers({ movers: [OP_NAMI, HANCOCK], movers_count: 2, unchanged_count: 294 }) });
    await renderPage();
    expect(screen.queryByTestId("movers-capped-note")).toBeNull();
  });

  it("shows two identically-capped movers with different raw moves but the same impact", async () => {
    await renderPage();
    // THE CASE THE WHOLE TWO-COLUMN LAYOUT EXISTS FOR. -41.18 % and -25.00 %
    // are very different card moves; both hit the cap, so the index counted
    // them identically. Both statements have to survive on screen.
    const law = rows()[0];
    const nami = rows()[1];
    expect(within(law).getByTestId("mover-raw-pct").textContent).not.toBe(
      within(nami).getByTestId("mover-raw-pct").textContent,
    );
    expect(within(law).getByTestId("mover-index-points").textContent).toBe(
      within(nami).getByTestId("mover-index-points").textContent,
    );
    expect(within(law).queryByTestId("mover-capped")).toBeTruthy();
    expect(within(nami).queryByTestId("mover-capped")).toBeTruthy();
  });
});

describe("days with nothing to show", () => {
  it("treats a zero-mover day as normal data, not an error", async () => {
    stub({ mov: quietDay() });
    await renderPage();
    expect(screen.getByTestId("movers-none").textContent).toBe(
      "No constituents moved on this Index day.",
    );
    expect(screen.queryByTestId("index-mover")).toBeNull();
    expect(screen.queryByTestId("movers-unavailable")).toBeNull();
    // The count line is still the real one - 296 constituents were compared.
    expect(screen.getByTestId("movers-meta").textContent).toBe(
      "Sep 6, 2026 · 0 of 296 constituents moved",
    );
  });

  it("renders no placeholder rows or empty columns on a quiet day", async () => {
    stub({ mov: quietDay() });
    await renderPage();
    const panel = screen.getByTestId("index-movers");
    expect(within(panel).queryByTestId("movers-list")).toBeNull();
    expect(within(panel).queryByTestId("mover-price-move")).toBeNull();
    expect(within(panel).queryByTestId("mover-index-impact")).toBeNull();
    expect(within(panel).queryByRole("img")).toBeNull();
  });

  it("says a base point has no prior day rather than that nothing moved", async () => {
    stub({ mov: basePoint() });
    await renderPage();
    expect(screen.getByTestId("movers-base-point").textContent).toContain(
      "This is the starting point of the Card Pirate Index. There is no prior day to compare.",
    );
    expect(screen.queryByTestId("movers-none")).toBeNull();
    expect(screen.queryByTestId("index-mover")).toBeNull();
  });

  it("keeps the base point distinguishable from a quiet day", async () => {
    stub({ mov: basePoint() });
    await renderPage();
    expect(screen.getByTestId("movers-meta").textContent).toBe(
      "Sep 3, 2026 · 0 of 0 constituents moved",
    );
  });
});

describe("failure is section-local", () => {
  it("a rejected movers request leaves the rest of Analytics rendered", async () => {
    stub({ movFails: true });
    await renderPage();
    expect(screen.getByTestId("movers-unavailable")).toBeTruthy();
    expect(screen.getByTestId("composition-count").textContent).toBe("296");
    expect(screen.getByTestId("market-breadth")).toBeTruthy();
    expect(screen.getByTestId("breadth-up").textContent).toBe("1");
    expect(screen.getByText("Card Pirate Index")).toBeTruthy();
  });

  it("a malformed payload fails locally rather than blanking Analytics", async () => {
    // `movers` absent entirely - mapping over an undefined would throw during
    // render, which React escalates into a blank page.
    stub({ mov: { as_of: "2026-09-07", constituent_count: 296 } });
    await renderPage();
    expect(screen.getByTestId("movers-unavailable")).toBeTruthy();
    expect(screen.getByTestId("composition-count").textContent).toBe("296");
    expect(screen.getByTestId("market-breadth")).toBeTruthy();
  });

  it("a null body fails locally too", async () => {
    stub({ mov: null });
    await renderPage();
    expect(screen.getByTestId("movers-unavailable")).toBeTruthy();
    expect(screen.getByTestId("index-analytics-row")).toBeTruthy();
  });
});

describe("request discipline", () => {
  it("fetches the movers exactly once on load", async () => {
    await renderPage();
    expect(calls("/analytics/index/movers")).toHaveLength(1);
  });

  it("asks for no window and no date", async () => {
    await renderPage();
    // The section describes the NEWEST published point. A window or a date in
    // this request would make it answer a different question from the one the
    // heading asks.
    expect(calls("/analytics/index/movers")[0][1]).toBeUndefined();
  });

  it("does not refetch when any of the seven timeframes is pressed", async () => {
    await renderPage();
    const group = within(screen.getByTestId("index-window"));
    const buttons = group.getAllByRole("button");
    expect(buttons).toHaveLength(7);
    const seriesBefore = calls("/analytics/index").length;
    for (const button of buttons) {
      fireEvent.click(button);
      await waitFor(() => expect(screen.getByTestId("index-movers")).toBeTruthy());
    }
    // THE PRESSES HAVE TO HAVE DONE SOMETHING, or this test passes for the
    // wrong reason. Every window in this suite's fixture is `available`, so
    // each press is a real window change and the SERIES is re-requested -
    // which is exactly the traffic the movers request must not join. (On live
    // staging most windows are unreachable and the control's own guard
    // suppresses the change, so a browser check there proves nothing.)
    expect(calls("/analytics/index").length).toBeGreaterThan(seriesBefore);
    expect(calls("/analytics/index/movers")).toHaveLength(1);
    // The composition's own guarantee, re-asserted here so this tranche
    // cannot regress it.
    expect(calls("/analytics/index/composition")).toHaveLength(1);
  });

  it("fetches no print or card endpoint to render the rows", async () => {
    await renderPage();
    const paths = apiGet.mock.calls.map((c) => c[0] as string);
    expect(paths.filter((p) => p.startsWith("/prints"))).toHaveLength(0);
    expect(paths.filter((p) => p.startsWith("/cards"))).toHaveLength(0);
    // Everything a row shows came from the one movers payload.
    expect(new Set(paths)).toEqual(
      new Set([
        "/analytics/index/movers",
        "/analytics/index/composition",
        "/analytics/index",
        "/analytics/market/bases",
        "/analytics/market/filters",
        "/analytics/market/overview",
      ]),
    );
  });
});

describe("placement and mobile structure", () => {
  it("sits below the composition and breadth row", async () => {
    await renderPage();
    const row = screen.getByTestId("index-analytics-row");
    const panel = screen.getByTestId("index-movers");
    // Node.DOCUMENT_POSITION_FOLLOWING === 4
    expect(row.compareDocumentPosition(panel) & 4).toBeTruthy();
  });

  it("keeps the two metric blocks separate children of every row", async () => {
    await renderPage();
    for (const row of rows()) {
      const move = within(row).getByTestId("mover-price-move");
      const impact = within(row).getByTestId("mover-index-impact");
      expect(move.parentElement).toBe(impact.parentElement);
      expect(move).not.toBe(impact);
    }
  });

  it("constrains every row's text so nothing can overflow the page", async () => {
    await renderPage();
    // `minmax(0,1fr)` on the identity column plus `min-w-0` on its content is
    // what stops a long card name pushing the metric columns off a 390px
    // viewport - a grid track defaults to `min-content` and would not shrink.
    for (const row of rows()) {
      expect(row.className).toContain("minmax(0,1fr)");
    }
    const identity = rows()[0].querySelector(".truncate");
    expect(identity).toBeTruthy();
  });

  it("stacks the metrics under the identity on mobile and inlines them on desktop", async () => {
    await renderPage();
    const metrics = within(rows()[0]).getByTestId("mover-price-move").parentElement!;
    // Mobile: second grid row of column 2. Desktop: the third column.
    expect(metrics.className).toContain("col-start-2");
    expect(metrics.className).toContain("sm:col-start-3");
  });
});
