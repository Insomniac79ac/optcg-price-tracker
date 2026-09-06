/** "Cards in this view" - the card strip on /analytics (Analytics 1C).
 *
 * WHAT THESE TESTS ARE ACTUALLY GUARDING. The strip's only job is to show a
 * few real cards from the scope the statistics above describe, and there are
 * exactly four ways to make it lie: price a card with a platform the collector
 * did not select, render a missing price as ¥0, keep the previous scope's
 * cards on screen after a filter changes, or crop the artwork so the card is
 * no longer the card. Each has a test below, and the fixtures are built so a
 * plausible refactor - not merely the original bug - would fail them.
 *
 * The selection itself is the SERVER's: `/prints?set=&rarity=&price_basis=`
 * decides which prints belong, so most assertions here are about what the page
 * ASKS for and what it does with the answer, never about re-deciding
 * eligibility on this side.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

import { formatJpy } from "@/lib/format";
import type { MarketBasis } from "@/lib/marketAnalytics";
import type { PrintCatalogueItem } from "@/lib/prints";

import MarketLandscapePage from "./page";

const BASES: MarketBasis[] = [
  {
    key: "market_index", kind: "market_index", source: null, reference_type: null,
    evidence_type: null, available: true, unavailable_reason: null, usable_priced_prints: 296,
  },
  {
    key: "source:yuyutei", kind: "source", source: "yuyutei", reference_type: "retail_sell",
    evidence_type: "listing", available: true, unavailable_reason: null, usable_priced_prints: 279,
  },
  {
    key: "source:snkrdunk", kind: "source", source: "snkrdunk", reference_type: "listing_floor",
    evidence_type: "listing", available: true, unavailable_reason: null, usable_priced_prints: 25,
  },
];

const FILTERS = {
  sets: [
    { value: "OP-01", label: "OP-01" },
    { value: "EB-02", label: "EB-02" },
  ],
  rarities: [
    { value: "R", label: "R" },
    { value: "L", label: "L" },
  ],
};

function overview(partial: Record<string, unknown> = {}) {
  return {
    price_basis: "market_index", kind: "market_index", source: null, reference_type: null,
    evidence_type: null, available: true, unavailable_reason: null,
    scope: { active_prints: 154, set: null, rarity: null },
    coverage: {
      observed_prints: null, usable_priced_prints: 81, coverage_pct: 52.6,
      excluded_constrained_prints: null, unavailable_prints: 73,
    },
    current_price: {
      constituent_count: 81, median_jpy: 80, p10_jpy: 30, p90_jpy: 220,
      unavailable_reason: null,
    },
    distribution: [{ lower_jpy: 0, upper_jpy: 99, label: "Under ¥100", count: 60 }],
    index_composition: { single_source_prints: 73, multi_source_prints: 8 },
    ...partial,
  };
}

/** One catalogue item in the real `/prints` shape.
 *
 * `sourceValues` is the important half: the same print carries a different
 * number for each platform, which is what makes a cross-source fallback
 * detectable rather than invisible.
 */
function item(
  id: number,
  code: string,
  name: string,
  opts: {
    index?: number | null;
    sourceValues?: Array<{
      source: string; value_jpy: number | null; eligible: boolean; reference_type: string;
    }>;
    rarity?: string | null;
    set?: string | null;
  } = {},
): PrintCatalogueItem {
  return {
    card_print_id: id,
    canonical_card_id: id,
    card_code: code,
    name_en: name,
    name_jp: null,
    rarity: opts.rarity ?? "R",
    canonical_rarity: opts.rarity ?? "R",
    card_type: "Character",
    treatment: "base",
    language: "jp",
    release_product_code: opts.set ?? "OP-01",
    original_set_code: "OP01",
    official_asset_variant: "base",
    image_url: `https://images.example.com/${code}.png`,
    display_image: null,
    verification_status: "verified",
    source_coverage: (opts.sourceValues ?? []).map((s) => s.source),
    latest_observation_at: null,
    market_index: {
      card_print_id: id,
      index_version: 3,
      source_semantics_version: 2,
      source_price_range: null,
      index_value_jpy: opts.index === undefined ? 1200 : opts.index,
      calculation_method: "median",
      source_count: 1,
      coverage_status: "limited",
      confidence: "medium",
      source_values: (opts.sourceValues ?? []).map((s) => ({
        source: s.source,
        reference_type: s.reference_type,
        evidence_type: "listing",
        value_jpy: s.value_jpy,
        observed_at: null,
        sample_size: null,
        stale: false,
        eligible: s.eligible,
        fallback_used: false,
        ineligible_reason: s.eligible ? null : "platform_minimum",
        constraint: s.eligible ? null : "platform_floor",
        contributes_to_index: s.eligible,
      })),
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-09-06T00:00:00Z",
    },
  } as unknown as PrintCatalogueItem;
}

function cardsResponse(items: PrintCatalogueItem[]) {
  return {
    items,
    total: items.length,
    limit: 6,
    offset: 0,
    pagination: { next_offset: null, prev_offset: null, has_more: false },
    facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
  };
}

const YUYU = { source: "yuyutei", value_jpy: 24800, eligible: true, reference_type: "retail_sell" };
const SNK = { source: "snkrdunk", value_jpy: 21000, eligible: true, reference_type: "listing_floor" };

/** The price string the app would render, produced by the app's own
 * formatter - never a hardcoded glyph, which is how the first version of
 * these tests missed that JPY formats with a FULL-WIDTH yen sign. */
function jpy(value: number) {
  return formatJpy(value);
}

function startAt(query: string) {
  window.history.replaceState(null, "", `/analytics${query ? `?${query}` : ""}`);
}

async function renderPage() {
  render(<MarketLandscapePage />);
  await waitFor(() => expect(screen.queryByText("Loading market landscape…")).toBeNull());
}

function strip() {
  return screen.getByRole("region", { name: "Cards in this view" });
}

beforeEach(() => {
  vi.clearAllMocks();
  startAt("");
  fetchMarketBases.mockResolvedValue({ bases: BASES });
  fetchMarketFilters.mockResolvedValue(FILTERS);
  fetchMarketOverview.mockResolvedValue(overview());
  fetchMarketCards.mockResolvedValue(
    cardsResponse([item(1, "OP01-001", "Luffy", { sourceValues: [YUYU, SNK] })]),
  );
});

// --- A. what the page asks the server for ----------------------------------

describe("the request carries the whole selection", () => {
  it("asks for the current basis, set and rarity", async () => {
    startAt("basis=source:snkrdunk&set=OP-01&rarity=R");
    await renderPage();
    await waitFor(() =>
      expect(fetchMarketCards).toHaveBeenCalledWith({
        priceBasis: "source:snkrdunk",
        set: "OP-01",
        rarity: "R",
      }),
    );
  });

  it("omits filters that are not set, rather than sending empty ones", async () => {
    await renderPage();
    await waitFor(() =>
      expect(fetchMarketCards).toHaveBeenCalledWith({
        priceBasis: "market_index",
        set: undefined,
        rarity: undefined,
      }),
    );
  });

  it("re-fetches when the basis changes", async () => {
    await renderPage();
    await waitFor(() => expect(fetchMarketCards).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /Yuyu-Tei/i }));
    await waitFor(() =>
      expect(fetchMarketCards).toHaveBeenLastCalledWith(
        expect.objectContaining({ priceBasis: "source:yuyutei" }),
      ),
    );
  });

  it("re-fetches when the set changes", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "OP-01" } });
    await waitFor(() =>
      expect(fetchMarketCards).toHaveBeenLastCalledWith(
        expect.objectContaining({ set: "OP-01" }),
      ),
    );
  });

  it("re-fetches when the rarity changes", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Rarity or special print"), {
      target: { value: "R" },
    });
    await waitFor(() =>
      expect(fetchMarketCards).toHaveBeenLastCalledWith(
        expect.objectContaining({ rarity: "R" }),
      ),
    );
  });

  it("never asks the client to sort or re-filter - the order is the server's", async () => {
    await renderPage();
    await waitFor(() => expect(fetchMarketCards).toHaveBeenCalled());
    // The helper hardcodes card_code_asc and the limit; the page passes only
    // the selection, so there is no place for a client-side ranking to enter.
    const call = fetchMarketCards.mock.calls[0][0];
    expect(Object.keys(call).sort()).toEqual(["priceBasis", "rarity", "set"]);
  });
});

// --- B. the price follows the basis, with no substitution -------------------

describe("the price shown is the selected basis, always", () => {
  it("shows the Market Index value under the Market Index basis", async () => {
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", { index: 22900, sourceValues: [YUYU, SNK] }),
      ]),
    );
    await renderPage();
    expect(await within(strip()).findByText(jpy(22900))).toBeInTheDocument();
    expect(within(strip()).queryByText(jpy(24800))).toBeNull();
    expect(within(strip()).queryByText(jpy(21000))).toBeNull();
  });

  it("shows the Yuyu-Tei value under the Yuyu-Tei basis", async () => {
    startAt("basis=source:yuyutei");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", { index: 22900, sourceValues: [YUYU, SNK] }),
      ]),
    );
    await renderPage();
    expect(await within(strip()).findByText(jpy(24800))).toBeInTheDocument();
    expect(within(strip()).queryByText(jpy(22900))).toBeNull();
    expect(within(strip()).queryByText(jpy(21000))).toBeNull();
  });

  it("shows the SNKRDUNK value under the SNKRDUNK basis", async () => {
    startAt("basis=source:snkrdunk");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", { index: 22900, sourceValues: [YUYU, SNK] }),
      ]),
    );
    await renderPage();
    expect(await within(strip()).findByText(jpy(21000))).toBeInTheDocument();
    expect(within(strip()).queryByText(jpy(24800))).toBeNull();
  });

  it("NEVER falls back to another platform's price", async () => {
    // The server would not return this print under a SNKRDUNK basis. If it
    // ever did, the card must say it has no SNKRDUNK price - not quietly show
    // the Yuyu-Tei one, and not show the index either.
    startAt("basis=source:snkrdunk");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([item(1, "OP01-001", "Luffy", { index: 22900, sourceValues: [YUYU] })]),
    );
    await renderPage();
    const region = strip();
    expect(within(region).queryByText(jpy(24800))).toBeNull();
    expect(within(region).queryByText(jpy(22900))).toBeNull();
    expect(within(region).getByText("Unavailable")).toBeInTheDocument();
  });

  it("an ineligible constrained reading is not shown as a price", async () => {
    startAt("basis=source:snkrdunk");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", {
          index: null,
          sourceValues: [
            { source: "snkrdunk", value_jpy: 1000, eligible: false, reference_type: "listing_floor" },
          ],
        }),
      ]),
    );
    await renderPage();
    expect(within(strip()).queryByText(jpy(1000))).toBeNull();
    expect(within(strip()).getByText("Unavailable")).toBeInTheDocument();
  });

  it("never fabricates ¥0", async () => {
    startAt("basis=source:snkrdunk");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([item(1, "OP01-001", "Luffy", { index: null, sourceValues: [] })]),
    );
    await renderPage();
    expect(within(strip()).queryByText(jpy(0))).toBeNull();
  });

  it("names the basis once, from the server's own words", async () => {
    startAt("basis=source:yuyutei");
    await renderPage();
    expect(within(strip()).getByText(/Prices shown are Yuyu-Tei · Retail price\./)).toBeInTheDocument();
  });

  it("renders a platform this build has never heard of generically", async () => {
    // No entry for "cardrush" in sourceDisplayName, none for "auction_high" in
    // the instrument vocabulary. Both must fall through to the server's own
    // tokens rather than blanking or reading "Unknown".
    fetchMarketBases.mockResolvedValue({
      bases: [
        ...BASES,
        {
          key: "source:cardrush", kind: "source", source: "cardrush",
          reference_type: "auction_high", evidence_type: "listing", available: true,
          unavailable_reason: null, usable_priced_prints: 3,
        },
      ],
    });
    startAt("basis=source:cardrush");
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", {
          index: 22900,
          sourceValues: [
            { source: "cardrush", value_jpy: 7777, eligible: true, reference_type: "auction_high" },
          ],
        }),
      ]),
    );
    await renderPage();
    const region = strip();
    expect(within(region).getByText(jpy(7777))).toBeInTheDocument();
    expect(within(region).getByText(/cardrush/)).toBeInTheDocument();
    expect(within(region).queryByText(/Unknown/)).toBeNull();
  });
});

// --- C. how many cards, and which -------------------------------------------

describe("the strip is small and shows only real results", () => {
  it("renders at most six", async () => {
    fetchMarketCards.mockResolvedValue(
      cardsResponse(
        Array.from({ length: 6 }, (_, i) =>
          item(i + 1, `OP01-00${i + 1}`, `Card ${i + 1}`, { sourceValues: [YUYU] }),
        ),
      ),
    );
    await renderPage();
    expect(await within(strip()).findAllByRole("listitem")).toHaveLength(6);
  });

  it("does not pad a short result up to six", async () => {
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", { sourceValues: [YUYU] }),
        item(2, "OP01-002", "Zoro", { sourceValues: [YUYU] }),
      ]),
    );
    await renderPage();
    expect(await within(strip()).findAllByRole("listitem")).toHaveLength(2);
  });

  it("renders the server's order verbatim", async () => {
    fetchMarketCards.mockResolvedValue(
      cardsResponse([
        item(1, "OP01-001", "Luffy", { sourceValues: [YUYU] }),
        item(2, "OP01-002", "Zoro", { sourceValues: [YUYU] }),
        item(3, "OP01-013", "Sanji", { sourceValues: [YUYU] }),
      ]),
    );
    await renderPage();
    const codes = within(strip())
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(codes[0]).toContain("OP01-001");
    expect(codes[1]).toContain("OP01-002");
    expect(codes[2]).toContain("OP01-013");
  });

  it("shows an honest empty state, not placeholders", async () => {
    fetchMarketCards.mockResolvedValue(cardsResponse([]));
    await renderPage();
    const region = strip();
    expect(within(region).getByText("No priced cards match this view yet.")).toBeInTheDocument();
    expect(within(region).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(region).queryByText(jpy(0))).toBeNull();
  });

  it("names the scope so the strip cannot be read as the whole catalogue", async () => {
    startAt("set=OP-01&rarity=R");
    await renderPage();
    expect(within(strip()).getByText(/OP-01 · R/)).toBeInTheDocument();
  });
});

// --- D. staleness -----------------------------------------------------------

describe("a filter change never leaves the previous scope's cards on screen", () => {
  it("clears the strip while the new scope loads", async () => {
    await renderPage();
    expect(await within(strip()).findByText("OP01-001")).toBeInTheDocument();

    // A request that never settles: the strip must not keep showing OP01-001
    // as though it belonged to the new set.
    fetchMarketCards.mockReturnValue(new Promise(() => {}));
    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "EB-02" } });

    await waitFor(() => expect(within(strip()).queryByText("OP01-001")).toBeNull());
  });

  it("a late response for an abandoned filter cannot overwrite a newer one", async () => {
    // A deferred whose resolver is captured OUTSIDE the executor: assigning it
    // inside narrows the binding to `never` for the later call.
    const slow: { resolve: (v: unknown) => void; promise: Promise<unknown> } = (() => {
      let resolve!: (v: unknown) => void;
      const promise = new Promise<unknown>((r) => {
        resolve = r;
      });
      return { resolve, promise };
    })();
    fetchMarketCards.mockImplementationOnce(() => slow.promise);
    await renderPage();

    // Move on before the first request settles; the second answers quickly.
    fetchMarketCards.mockResolvedValue(
      cardsResponse([item(9, "EB02-009", "Later", { sourceValues: [YUYU] })]),
    );
    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "EB-02" } });
    expect(await within(strip()).findByText("EB02-009")).toBeInTheDocument();

    // The abandoned first request lands last. It must be ignored.
    slow.resolve(cardsResponse([item(1, "OP01-001", "Stale", { sourceValues: [YUYU] })]));
    await waitFor(() => expect(within(strip()).queryByText("OP01-001")).toBeNull());
    expect(within(strip()).getByText("EB02-009")).toBeInTheDocument();
  });

  it("a card-strip failure does not take the statistics down", async () => {
    fetchMarketCards.mockRejectedValue(new Error("boom"));
    await renderPage();
    expect(await screen.findByText(jpy(80))).toBeInTheDocument();
    expect(within(strip()).getByText(/could not be loaded/)).toBeInTheDocument();
  });
});

// --- E. artwork and genericity ----------------------------------------------

describe("the artwork is the card, whole", () => {
  it("renders the full card with contain-style fitting, never a crop", async () => {
    await renderPage();
    const img = await within(strip()).findByAltText("Luffy (OP01-001)");
    expect(img.className).toContain("object-contain");
    expect(img.className).not.toContain("object-cover");
  });

  it("never crops on the verified-geometry path either", async () => {
    // Staging serves most artwork with a verified card box, which puts
    // CardImageFrame into its BOUNDED mode: the card is fitted to the frame
    // and only the canvas it was composited onto is clipped away. That is the
    // shared component's own no-crop contract (and its own tests cover the
    // geometry maths) - what matters here is that routing a card through this
    // strip cannot turn it into a cover-fit crop.
    const withGeometry = item(1, "OP01-001", "Luffy", { sourceValues: [YUYU] });
    (withGeometry as unknown as { display_image: unknown }).display_image = {
      url: "https://images.example.com/OP01-001.png",
      source: "official",
      exact_print_verified: true,
      owned_asset_selected: false,
      geometry: {
        canvas_px: { width: 856, height: 625 },
        card_bbox_px: { x: 241, y: 51, width: 374, height: 523 },
      },
    };
    fetchMarketCards.mockResolvedValue(cardsResponse([withGeometry]));
    await renderPage();
    const img = await within(strip()).findByAltText("Luffy (OP01-001)");
    expect(img.className).not.toContain("object-cover");
  });

  it("introduces no source-name allowlist or stored price_type mapping", async () => {
    const fs = await import("fs/promises");
    const [cards, lib] = await Promise.all([
      fs.readFile("src/components/ui/MarketLandscapeCards.tsx", "utf8"),
      fs.readFile("src/lib/marketAnalytics.ts", "utf8"),
    ]);
    for (const source of [cards, lib]) {
      const code = source
        .split("\n")
        .filter((line) => !line.trim().startsWith("*") && !line.trim().startsWith("//"))
        .join("\n");
      // Stored price_type tokens must never appear: the client reads
      // reference_type/evidence_type, which are the published vocabulary.
      expect(code).not.toMatch(/["']sell["']|["']floor["']|["']buy["']/);
      // And no platform may be branched on.
      expect(code.toLowerCase()).not.toMatch(/if\s*\(.*(yuyutei|snkrdunk)/);
    }
  });
});
