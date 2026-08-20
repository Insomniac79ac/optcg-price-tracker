import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/prints/1",
  useSearchParams: () => new URLSearchParams(""),
  useParams: () => ({ id: "1" }),
}));

const { fetchPrint } = vi.hoisted(() => ({ fetchPrint: vi.fn() }));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrint };
});

// Guard: the print detail page must never reach for a legacy card_id-keyed
// endpoint, which merges sibling prints into one price.
const { fetchCardMarketIndex, fetchCard } = vi.hoisted(() => ({
  fetchCardMarketIndex: vi.fn(),
  fetchCard: vi.fn(),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchCardMarketIndex, fetchCard };
});

import { ApiError } from "@/lib/api";
import type {
  PrintDetail,
  PrintMarketIndex,
  PrintMarketIndexSourceValue,
} from "@/lib/prints";

import PrintDetailPage from "./page";

function sourceValue(
  overrides: Partial<PrintMarketIndexSourceValue> & { source: string },
): PrintMarketIndexSourceValue {
  return {
    reference_type: overrides.source === "snkrdunk" ? "listing_floor" : "retail_sell",
    evidence_type: "listing",
    value_jpy: null,
    observed_at: "2026-08-16T18:22:15.170718Z",
    sample_size: null,
    stale: false,
    eligible: true,
    fallback_used: false,
    ineligible_reason: null,
    ...overrides,
  };
}

const DISPLAY_IMAGE_URL =
  "https://pub-74ceb3c7e49b4c008c58bcfa36d4d38d.r2.dev/display-images/sha256/00/zoro.webp";

/** Shaped on the real `GET /prints/1` staging payload. */
function makeDetail(overrides: Partial<PrintDetail> = {}): PrintDetail {
  const index: PrintMarketIndex = {
    card_print_id: 1,
    index_version: 1,
    index_value_jpy: 26900,
    calculation_method: "median_of_sources",
    source_count: 2,
    coverage_status: "full",
    confidence: "high",
    source_values: [
      sourceValue({ source: "yuyutei", value_jpy: 29800 }),
      sourceValue({ source: "snkrdunk", value_jpy: 24000, fallback_used: true }),
    ],
    auxiliary_values: [],
    freshest_observation_at: "2026-08-16T19:21:31.777842Z",
    stalest_eligible_source_at: "2026-08-16T18:22:15.170718Z",
    stale_sources: [],
    calculated_at: "2026-08-17T13:59:14.526838Z",
    ...overrides.market_index,
  };

  return {
    card_print_id: 1,
    canonical_card_id: 2,
    card_code: "OP01-001",
    name_en: "Roronoa Zoro",
    name_jp: "ロロノア・ゾロ",
    rarity: "L",
    card_type: "Leader",
    colors: ["Red"],
    language: "jp",
    treatment: "parallel",
    release_product_code: "OP-01",
    artwork_key: "4b2462f2b042a020",
    image_url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
    display_image: {
      url: DISPLAY_IMAGE_URL,
      source: "snkrdunk",
      exact_print_verified: true,
      geometry: {
        canvas_px: { width: 856, height: 625 },
        card_bbox_px: { x: 241, y: 51, width: 374, height: 523 },
      },
    },
    verification_status: "verified",
    siblings: [],
    ...overrides,
    market_index: index,
  };
}

afterEach(() => vi.clearAllMocks());

/** The card image specifically - the page's brand texture is tagged
 * data-brand-asset. */
function cardImage(container: HTMLElement): HTMLImageElement | null {
  return container.querySelector("img:not([data-brand-asset])");
}

describe("print detail page", () => {
  it("shows this print's own verified artwork, whole and uncropped", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    // Exactly the display image the API resolved for this print - never the
    // canonical URL, never a sibling's artwork.
    const img = cardImage(container)!;
    expect(img.getAttribute("src")).toBe(DISPLAY_IMAGE_URL);
    // Bounded-geometry presentation scales by width only, so the card keeps
    // its aspect ratio and all four edges; nothing may cover or clip it.
    expect(img.className).not.toContain("object-cover");
    expect(img.style.height).toBe("");
    // The decorative map texture behind the page is allowed to cover; no
    // card image ever is.
    expect(
      container.querySelector("img:not([data-brand-asset])[class*='object-cover']"),
    ).toBeNull();
  });

  it("never reaches for a legacy card_id-keyed endpoint", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);

    await waitFor(() => expect(fetchPrint).toHaveBeenCalledWith("1"));
    expect(fetchCardMarketIndex).not.toHaveBeenCalled();
    expect(fetchCard).not.toHaveBeenCalled();
  });

  it("leads the money with the Market Index and no fabricated movement", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByRole("heading", { name: "Market Index" })).toBeTruthy();
    expect(screen.getByText("￥26,900").className).toContain("text-accent-gold");
    // The payload carries no history, so nothing may imply any.
    expect(container.textContent).not.toMatch(/[+-]\d+(\.\d+)?%/);
    expect(container.textContent).not.toMatch(/\b(24h|7d|30d|trend)\b/i);
    expect(container.querySelector("svg.sparkline")).toBeNull();
  });

  it("says the index is unavailable rather than showing ¥0", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: null,
          source_count: 0,
          coverage_status: "none",
          confidence: "low",
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: null, observed_at: null }),
            sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
          ],
        } as PrintMarketIndex,
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("Index unavailable")).toBeTruthy();
    expect(container.textContent).not.toMatch(/￥0\b/);
    // No source reported, so there is no source panel to show either.
    expect(screen.queryByRole("heading", { name: "Market sources" })).toBeNull();
  });

  it("names what each source price actually is, never reinterpreting one for another", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("Yuyu-Tei")).toBeTruthy();
    expect(within(sources).getByText("￥29,800")).toBeTruthy();
    expect(within(sources).getByText(/Retail sell price/)).toBeTruthy();

    expect(within(sources).getByText("SNKRDUNK")).toBeTruthy();
    expect(within(sources).getByText("￥24,000")).toBeTruthy();
    // A floor listing is never described as a completed sale.
    expect(within(sources).getByText(/Lowest listing/)).toBeTruthy();
    expect(sources.textContent).not.toMatch(/sold|sale/i);
  });

  it("shows a single source panel for a one-source print, with no empty second panel", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 120,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 120 }),
            sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
          ],
        } as PrintMarketIndex,
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("Yuyu-Tei")).toBeTruthy();
    expect(within(sources).queryByText("SNKRDUNK")).toBeNull();
    expect(sources.textContent).not.toMatch(/￥0\b/);
    // One source, one panel - the layout must not reserve a second column.
    expect(sources.querySelector(".sm\\:grid-cols-2")).toBeNull();
  });

  it("always states the treatment in the API's own word, including a plain printing", async () => {
    fetchPrint.mockResolvedValue(makeDetail({ treatment: "normal" }));
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    // Two separate printings are two separate collectibles, so "normal" is
    // shown as-is and never relabelled "base" or dropped.
    expect(screen.getAllByText("normal").length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/\bbase\b/i);
  });

  it("describes the print only with fields the payload actually carries", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const about = screen.getByRole("heading", { name: "About this print" }).parentElement!;
    for (const term of ["Card code", "Set", "Rarity", "Treatment", "Card type", "Colour", "Language"]) {
      expect(within(about).getByText(term)).toBeTruthy();
    }
    expect(within(about).getByText("OP01-001")).toBeTruthy();
    expect(within(about).getByText("Leader")).toBeTruthy();
    expect(within(about).getByText("Red")).toBeTruthy();
    // GET /prints/{id} returns no cost, power, attribute or effect text.
    expect(about.textContent).not.toMatch(/\b(Cost|Power|Attribute|Effect|Counter)\b/);
  });

  it("keeps the metadata in the identity column, after the prices", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        siblings: [
          {
            card_print_id: 4,
            treatment: "normal",
            artwork_key: null,
            image_url: null,
            verification_status: "verified",
          },
        ],
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" });
    const sources = screen.getByRole("heading", { name: "Market sources" });
    const about = screen.getByRole("heading", { name: "About this print" });
    const others = screen.getByRole("heading", { name: "Other printings" });

    // One reading order at every width: identity, money, sources, then the
    // print's own attributes.
    const order = (el: Element) => [...document.querySelectorAll("h1, h2")].indexOf(el);
    expect(order(index)).toBeLessThan(order(sources));
    expect(order(sources)).toBeLessThan(order(about));

    // The attributes share the column the prices are in, so the column runs
    // the height of the card beside it rather than stopping short.
    const column = sources.closest("div.min-w-0")!;
    expect(column.contains(about)).toBe(true);
    // Other printings is about other prints, so it stays outside that column.
    expect(column.contains(others)).toBe(false);
    expect(order(about)).toBeLessThan(order(others));
  });

  it("dates the index with its real freshest observation", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    // Copy changed; the timestamp behind it did not.
    expect(screen.getByText("Updated Aug 16, 2026")).toBeTruthy();
  });

  it("shows the Japanese name when the payload has one", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("ロロノア・ゾロ")).toBeTruthy();
  });

  it("links back to the catalogue", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByRole("link", { name: /Catalogue/ }).getAttribute("href")).toBe("/cards");
  });

  it("lists other printings only when the API sends them", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { unmount } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });
    expect(screen.queryByRole("heading", { name: "Other printings" })).toBeNull();
    unmount();

    fetchPrint.mockResolvedValue(
      makeDetail({
        siblings: [
          {
            card_print_id: 4,
            treatment: "normal",
            artwork_key: null,
            image_url: null,
            verification_status: "verified",
          },
        ],
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Other printings" });
    expect(screen.getByRole("link", { name: "normal" }).getAttribute("href")).toBe("/prints/4");
  });

  it("surfaces a failure rather than an empty page", async () => {
    fetchPrint.mockRejectedValue(new Error("boom"));
    render(<PrintDetailPage />);

    expect(await screen.findByText("This print couldn’t be loaded right now.")).toBeTruthy();
  });

  it("tells a visitor a print does not exist rather than blaming the network", async () => {
    // A stale/mistyped /prints/{id} is a 404, not an outage - offering a
    // Retry there would only fail again.
    fetchPrint.mockRejectedValue(new ApiError("Not Found", 404));
    render(<PrintDetailPage />);

    expect(await screen.findByText("This print isn’t in the Atlas.")).toBeTruthy();
    expect(screen.queryByText("This print couldn’t be loaded right now.")).toBeNull();
    expect(screen.getByRole("link", { name: /Browse the catalogue/ })).toBeTruthy();
  });

  // --- constrained source prices (Task 1C-2E) ------------------------------
  //
  // The real staging shape for print 5 (Portgas D. Ace OP02-013): a genuine
  // Yuyu-Tei price of ¥220 beside a SNKRDUNK floor sitting exactly on that
  // platform's ¥1,000 minimum, which the backend excluded from the index.
  // Before this tranche the page showed both numbers and explained nothing,
  // so a ¥220 index next to a ¥1,000 source read as a bug.

  function constrainedDetail() {
    return makeDetail({
      market_index: {
        index_value_jpy: 220,
        source_count: 1,
        coverage_status: "limited",
        confidence: "medium",
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 220 }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 1000,
            fallback_used: true,
            eligible: false,
            ineligible_reason: "platform_floor",
            constraint: "platform_floor",
          }),
        ],
      } as PrintMarketIndex,
    });
  }

  it("explains a platform-floor price instead of leaving the gap unexplained", async () => {
    fetchPrint.mockResolvedValue(constrainedDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;

    // The index and both raw prices are all still on the page: the ¥1,000 is
    // explained, never hidden, and the index is the backend's own ¥220.
    // ¥220 appears twice on purpose: as the index and as its one source.
    expect(screen.getAllByText("￥220").length).toBeGreaterThan(1);
    expect(within(sources).getByText("￥1,000")).toBeTruthy();
    expect(within(sources).getByText("SNKRDUNK")).toBeTruthy();

    expect(within(sources).getByText("Minimum listing price")).toBeTruthy();
    expect(
      within(sources).getByText(
        /at the source's minimum listing price and may not reflect the card's actual market price/,
      ),
    ).toBeTruthy();
    expect(within(sources).getByText("Not used in Market Index")).toBeTruthy();

    // The explanation names no source and quotes no threshold - the source's
    // identity is already on screen from the API's own data, and the rule
    // itself belongs to the backend (Task 1C-2E2).
    const note = within(sources).getByText("Minimum listing price").parentElement!;
    expect(note.textContent).not.toMatch(/SNKRDUNK/i);
    expect(note.textContent).not.toMatch(/[0-9]/);
  });

  it("never renders a backend constraint name to a collector", async () => {
    fetchPrint.mockResolvedValue(constrainedDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/platform_floor|below_platform_minimum/);
  });

  it("marks a below-minimum price as an anomaly while keeping the raw value", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 220,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 220 }),
            sourceValue({
              source: "snkrdunk",
              value_jpy: 999,
              fallback_used: true,
              eligible: false,
              ineligible_reason: "below_platform_minimum",
              constraint: "below_platform_minimum",
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("￥999")).toBeTruthy();
    expect(within(sources).getByText("Source data anomaly")).toBeTruthy();
    expect(
      within(sources).getByText(
        /below the source's known minimum and is not used in Market Index/,
      ),
    ).toBeTruthy();
    expect(container.textContent).not.toMatch(/below_platform_minimum/);
    // Its own sentence already says it - the generic line would just repeat.
    expect(within(sources).queryByText("Not used in Market Index")).toBeNull();
  });

  it("stays quiet and functional for a constraint it has never heard of", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 220,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 220 }),
            sourceValue({
              source: "snkrdunk",
              value_jpy: 1234,
              eligible: false,
              ineligible_reason: "future_constraint",
              constraint: "future_constraint",
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    // The price survives, no invented meaning, no leaked identifier - and the
    // one thing we do know (it did not count) is still said.
    expect(within(sources).getByText("￥1,234")).toBeTruthy();
    expect(container.textContent).not.toMatch(/future_constraint/);
    expect(within(sources).getByText("Not used in Market Index")).toBeTruthy();
  });

  it("leaves an ordinary source panel exactly as it was", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("￥29,800")).toBeTruthy();
    expect(within(sources).getByText("￥24,000")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Minimum listing price|Source data anomaly/);
    expect(container.textContent).not.toMatch(/Not used in Market Index/);
  });

  // --- source price range (Task 2A-3) --------------------------------------
  //
  // Real staging shapes: print 7 (index ¥810 from ¥120 and ¥1,500 - the case
  // this line exists for) and print 5 (index ¥220, one eligible source, so the
  // backend sends null).

  function withRange(range: unknown, overrides: Record<string, unknown> = {}) {
    return makeDetail({
      market_index: {
        index_value_jpy: 810,
        source_count: 2,
        coverage_status: "full",
        confidence: "high",
        source_price_range: range,
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120 }),
          sourceValue({ source: "snkrdunk", value_jpy: 1500, fallback_used: true }),
        ],
        ...overrides,
      } as PrintMarketIndex,
    });
  }

  it("shows the span of the sources behind the index", async () => {
    fetchPrint.mockResolvedValue(withRange({ low_jpy: 120, high_jpy: 1500 }));
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" }).parentElement!;
    expect(within(index).getByText(/Source range/)).toBeTruthy();
    expect(within(index).getByText("￥120 – ￥1,500")).toBeTruthy();
    // The index itself is untouched and still the loudest figure.
    expect(within(index).getByText("￥810")).toBeTruthy();
  });

  it("prints a single figure when both sources agree exactly", async () => {
    fetchPrint.mockResolvedValue(
      withRange({ low_jpy: 1500, high_jpy: 1500 }, { index_value_jpy: 1500 }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" }).parentElement!;
    // Twice inside the block on purpose: the index value itself, and the range
    // line stating the single figure both sources agreed on.
    expect(within(index).getAllByText("￥1,500")).toHaveLength(2);
    expect(within(index).getByText(/Source range/)).toBeTruthy();
    // Never "￥1,500 – ￥1,500".
    expect(container.textContent).not.toMatch(/￥1,500 – ￥1,500/);
  });

  it("renders nothing when the backend sends a null range", async () => {
    // Print 5's real shape: one eligible source, so there is no span to state.
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 220,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_price_range: null,
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 220 }),
            sourceValue({
              source: "snkrdunk", value_jpy: 1000, eligible: false,
              ineligible_reason: "platform_floor", constraint: "platform_floor",
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/Source range/);
    // ...and the rest of the page is unaffected.
    expect(screen.getAllByText("￥220").length).toBeGreaterThan(0);
    expect(screen.getByText("Minimum listing price")).toBeTruthy();
  });

  it("stays safe against an API that predates the field", async () => {
    // The currently deployed backend omits source_price_range entirely.
    const detail = withRange(undefined);
    delete (detail.market_index as unknown as Record<string, unknown>).source_price_range;
    fetchPrint.mockResolvedValue(detail);
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/Source range/);
    expect(screen.getByText("￥810")).toBeTruthy();
  });

  it("leaves the existing Market Index block otherwise unchanged", async () => {
    fetchPrint.mockResolvedValue(withRange({ low_jpy: 120, high_jpy: 1500 }));
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" }).parentElement!;
    // Index, its date caption and the source panels all still render.
    expect(within(index).getByText("￥810")).toBeTruthy();
    expect(within(index).getByText(/Updated/)).toBeTruthy();
    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("￥1,500")).toBeTruthy();
    expect(within(sources).getByText(/Lowest listing/)).toBeTruthy();
  });
});
