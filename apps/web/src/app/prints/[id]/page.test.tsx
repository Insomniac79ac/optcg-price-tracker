import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    canonical_rarity: "L",
    card_type: "Leader",
    colors: ["Red"],
    language: "jp",
    treatment: "parallel",
    release_product_code: "OP-01",
    original_set_code: "OP-01",
    official_asset_variant: "base",
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

  it("renders an unclassified printing with no treatment chip and no invented label", async () => {
    // treatment: null means Atlas has not classified this printing. No badge,
    // no "Unclassified" copy, no fallback word - and the rest of the identity
    // renders exactly as it does for a classified print.
    fetchPrint.mockResolvedValue(makeDetail({ treatment: null }));
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/unclassified|unknown|null|undefined/i);
    expect(screen.queryByText("parallel")).toBeNull();
    expect(screen.queryByText("Treatment")).toBeNull();

    // Identity and artwork are unaffected.
    expect(screen.getAllByText("OP01-001").length).toBeGreaterThan(0);
    expect(cardImage(container)!.getAttribute("src")).toBe(DISPLAY_IMAGE_URL);
  });

  it("states the printing type from the asset variant, not the raw treatment word", async () => {
    // "treatment" is Atlas's internal classification and is NULL on every
    // imported print, so it can never be the thing that tells two printings
    // apart. Bandai's own asset variant can.
    fetchPrint.mockResolvedValue(
      makeDetail({ treatment: "parallel", official_asset_variant: "p1" }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getAllByText("Alt Art").length).toBeGreaterThan(0);
    expect(screen.getByText("Printing")).toBeTruthy();
    expect(screen.queryByText("Treatment")).toBeNull();
    expect(screen.queryByText("parallel")).toBeNull();
  });

  it("omits an unclassified sibling rather than labelling it", async () => {
    // The treatment is this chip's only text, and there is no honest label
    // for an unclassified printing - so the chip is not rendered at all.
    // No "#12", no "Unclassified", no invented word.
    fetchPrint.mockResolvedValue(
      makeDetail({
        siblings: [
          {
            card_print_id: 12,
            treatment: null,
            artwork_key: null,
            image_url: null,
            verification_status: "verified",
          },
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.queryByRole("link", { name: "#12" })).toBeNull();
    expect(container.querySelector('a[href="/prints/12"]')).toBeNull();
    expect(container.textContent).not.toMatch(/unclassified|unknown|#12/i);
    // With no labelled sibling left, the section says nothing at all.
    expect(screen.queryByText("Other printings")).toBeNull();
  });

  it("still lists a classified sibling beside an unclassified one", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        siblings: [
          {
            card_print_id: 12,
            treatment: null,
            artwork_key: null,
            image_url: null,
            verification_status: "verified",
          },
          {
            card_print_id: 13,
            treatment: "normal",
            artwork_key: null,
            image_url: null,
            verification_status: "verified",
          },
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("Other printings")).toBeTruthy();
    const link = screen.getByRole("link", { name: "normal" });
    expect(link.getAttribute("href")).toBe("/prints/13");
    expect(container.querySelector('a[href="/prints/12"]')).toBeNull();
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
    expect(within(sources).getByText(/Retail price/)).toBeTruthy();

    expect(within(sources).getByText("SNKRDUNK")).toBeTruthy();
    expect(within(sources).getByText("￥24,000")).toBeTruthy();
    // A floor listing is never described as a completed sale - the label says
    // "Current listing", which is what it is.
    expect(within(sources).getByText(/Current listing/)).toBeTruthy();
    expect(sources.textContent).not.toMatch(/sold|sale/i);
  });

  it("names the source that reported nothing beside the one that did, with no invented price", async () => {
    // The panel used to be dropped entirely, which left a print Yuyu-Tei
    // priced and SNKRDUNK did not looking exactly like a print SNKRDUNK had
    // never been asked about. The absence is now stated.
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
    expect(within(sources).getByText("SNKRDUNK")).toBeTruthy();
    expect(within(sources).getByText("Price unavailable")).toBeTruthy();
    expect(sources.textContent).not.toMatch(/￥0\b/);
  });

  it("gives a base printing no printing badge at all", async () => {
    // Its absence is the signal: the Alt Art beside it is the different one.
    fetchPrint.mockResolvedValue(
      makeDetail({ treatment: "normal", official_asset_variant: "base" }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.queryByText("Alt Art")).toBeNull();
    expect(screen.queryByText("Reprint")).toBeNull();
    expect(screen.queryByText("Printing")).toBeNull();
    // The internal words never reach the page either way.
    expect(container.textContent).not.toMatch(/\bnormal\b|\btreatment\b/i);
  });

  it("describes the print only with fields the payload actually carries", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const about = screen
      .getByRole("heading", { name: "About this print" })
      .closest("section")!;
    for (const term of ["Card code", "Set", "Found in", "Rarity", "Card type", "Colour", "Language"]) {
      expect(within(about).getByText(term)).toBeTruthy();
    }
    expect(within(about).getByText("OP01-001")).toBeTruthy();
    // Rarity "L" now reads "Leader", the same word as the card type - so each
    // is asserted as a term/value pair rather than by a bare text lookup.
    expect(within(about).getAllByText("Leader").length).toBe(2);
    expect(within(about).getByText("Red")).toBeTruthy();
    // GET /prints/{id} returns no cost, power, attribute or effect text.
    expect(about.textContent).not.toMatch(/\b(Cost|Power|Attribute|Effect|Counter)\b/);
  });

  /** The rows of "About this print", as term -> value, in document order.
   * The whole point of this tranche is which rows exist and what each one
   * says, so the tests read them off the page rather than probing for text. */
  function aboutRows(): [string, string][] {
    const about = screen
      .getByRole("heading", { name: "About this print" })
      .closest("section")!;
    return Array.from(about.querySelectorAll("dl > div")).map((row) => [
      row.querySelector("dt")!.textContent!,
      row.querySelector("dd")!.textContent!,
    ]);
  }

  it("states an SP Card's rarity and its special print as two separate rows", async () => {
    // OP06-007 Shanks: published as SPカード in PRB-02, Super Rare under its
    // own set OP-06, and Bandai's p2 asset. Three independent facts.
    fetchPrint.mockResolvedValue(
      makeDetail({
        card_code: "OP06-007",
        name_en: "Shanks",
        name_jp: "シャンクス",
        rarity: "SPカード",
        canonical_rarity: "SR",
        card_type: "Character",
        release_product_code: "PRB-02",
        original_set_code: "OP-06",
        official_asset_variant: "p2",
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Shanks", level: 1 });

    expect(aboutRows()).toEqual([
      ["Card code", "OP06-007"],
      ["Set", "OP-06"],
      ["Found in", "PRB-02"],
      ["Rarity", "Super Rare"],
      ["Special print", "SP Card"],
      ["Printing", "Alt Art"],
      ["Card type", "Character"],
      ["Colour", "Red"],
      ["Language", "Japanese"],
    ]);
    // And never the raw token, anywhere a collector reads.
    expect(document.body.textContent).not.toContain("SPカード");
  });

  it("omits the Rarity row for a TR print rather than inventing one", async () => {
    // OP16-042: the catalogue establishes no card-level rarity, so there is
    // no underlying rarity to show and none is guessed from the product, the
    // asset variant or a sibling.
    fetchPrint.mockResolvedValue(
      makeDetail({
        card_code: "OP16-042",
        name_en: "Prisoner of Impel Down",
        name_jp: "インペルダウンの囚人",
        rarity: "TR",
        canonical_rarity: null,
        card_type: "Character",
        release_product_code: "OP-16",
        original_set_code: "OP-16",
        official_asset_variant: "p1",
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Prisoner of Impel Down", level: 1 });

    expect(aboutRows()).toEqual([
      ["Card code", "OP16-042"],
      ["Set", "OP-16"],
      ["Found in", "OP-16"],
      ["Special print", "Treasure Rare"],
      ["Printing", "Alt Art"],
      ["Card type", "Character"],
      ["Colour", "Red"],
      ["Language", "Japanese"],
    ]);
    expect(aboutRows().map(([term]) => term)).not.toContain("Rarity");
  });

  it("omits the Set row for a promo, which belongs to no numbered set", async () => {
    // P-105 Sabo, the single SP P print: no original set, no card-level
    // rarity, and a rarity token that names a special print. Two rows absent,
    // neither dashed.
    fetchPrint.mockResolvedValue(
      makeDetail({
        card_code: "P-105",
        name_en: "Sabo",
        name_jp: "サボ",
        rarity: "SP P",
        canonical_rarity: null,
        card_type: "Character",
        release_product_code: "OP-15",
        original_set_code: null,
        official_asset_variant: "p2",
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Sabo", level: 1 });

    expect(aboutRows()).toEqual([
      ["Card code", "P-105"],
      ["Found in", "OP-15"],
      ["Special print", "SP Card"],
      ["Printing", "Alt Art"],
      ["Card type", "Character"],
      ["Colour", "Red"],
      ["Language", "Japanese"],
    ]);
    expect(document.body.textContent).not.toContain("SP P");
  });

  it("shows an unrecognised rarity token verbatim rather than dropping it", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({ rarity: "XR", canonical_rarity: null, card_type: "Character" }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const rows = Object.fromEntries(aboutRows());
    expect(rows["Published rarity"]).toBe("XR");
    expect(rows["Rarity"]).toBeUndefined();
    expect(rows["Special print"]).toBeUndefined();
  });

  it("offers the terminology key on the page, not only on the catalogue", async () => {
    // The detail page is where "Super Rare" and "SP Card" sit next to each
    // other, so the explanation has to be reachable here without a hover.
    fetchPrint.mockResolvedValue(makeDetail({ rarity: "SPカード", canonical_rarity: "SR" }));
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });
    toggle.click();
    await waitFor(() =>
      expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy(),
    );
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
    expect(within(sources).getByText(/Current listing/)).toBeTruthy();
  });
});

/** GUARD: the print detail page renders no reliability claim.
 *
 * `market_index.confidence` is contributor-count metadata - it reads "high"
 * the moment two sources contribute, whether they agree to the yen or disagree
 * by 20x, and it carries no information `coverage_status` does not (see
 * src/lib/marketIndexConfidence.test.ts for the full contract and the static
 * scan that enforces it).
 *
 * This is the behavioural half of that guard on the page with the most room to
 * over-explain. What the page SHOULD say about disagreement it already says,
 * with the field that measures it: "Source range ¥120 – ¥2,500". A grade would
 * add nothing and would claim something the backend never computed. */
describe("print detail page - no reliability claim", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  /** The real ¥120 / ¥2,500 staging shape, at v3: both eligible, both
   * contributing, 20x apart, and the backend duly reports full/high. */
  function wideDisagreement() {
    return makeDetail({
      market_index: {
        index_value_jpy: 1310,
        source_count: 2,
        coverage_status: "full",
        confidence: "high",
        source_price_range: { low_jpy: 120, high_jpy: 2500 },
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120, contributes_to_index: true }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 2500,
            fallback_used: true,
            contributes_to_index: true,
          }),
        ],
      } as PrintMarketIndex,
    });
  }

  it("renders no confidence, quality or reliability language", async () => {
    fetchPrint.mockResolvedValue(wideDisagreement());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/confidence/i);
    expect(text).not.toMatch(/reliab|accurate|trustworth|certainty/i);
    // Nor the coverage vocabulary the confidence value mirrors 1:1.
    expect(text).not.toMatch(/full coverage|limited coverage|\d+ sources\b/i);
  });

  it("communicates the disagreement with the field that measures it", async () => {
    // The honest answer to "how much should I trust ¥1,310?" is the spread it
    // sits inside, published as a measured fact rather than a grade.
    fetchPrint.mockResolvedValue(wideDisagreement());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText(/Source range/)).toBeTruthy();
    expect(screen.getByText("￥120 – ￥2,500")).toBeTruthy();
    expect(screen.getByText("￥1,310")).toBeTruthy();
  });
});

/** Market Index v3: what kind of evidence each source price IS, said neutrally.
 *
 * v2 answered a ¥2,500 SNKRDUNK listing beside a ¥120 index by giving the
 * listing no weight and stamping it "Reference only". v3 counts it, so the
 * page has to do the harder thing instead: say plainly that a current asking
 * price is not a completed sale, without implying anything is wrong with it.
 * That is what these labels and their explanations are for.
 */
describe("print detail page - evidence types", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  /** A v3 payload: BOTH sources eligible, both contributing, the index their
   * midpoint. Yuyu-Tei asks ¥24,800, SNKRDUNK's cheapest open listing is
   * ¥20,500, and ¥22,650 is the middle. */
  function twoAskingSources() {
    return makeDetail({
      market_index: {
        index_value_jpy: 22650,
        source_count: 2,
        coverage_status: "full",
        confidence: "high",
        source_price_range: { low_jpy: 20500, high_jpy: 24800 },
        source_values: [
          sourceValue({
            source: "yuyutei",
            value_jpy: 24800,
            contributes_to_index: true,
          }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 20500,
            fallback_used: true,
            contributes_to_index: true,
          }),
        ],
      } as PrintMarketIndex,
    });
  }

  it("names each price as the kind of evidence it is", async () => {
    fetchPrint.mockResolvedValue(twoAskingSources());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText(/Retail price/)).toBeTruthy();
    expect(within(sources).getByText(/Current listing/)).toBeTruthy();
  });

  it("says nothing is wrong with a listing that fed the index", async () => {
    // THE POINT OF v3 ON THIS PAGE. The SNKRDUNK value is an asking price, it
    // is labelled as one, and it counted - so "Reference only" must be gone
    // from it. Under v2 this exact row carried that chip.
    fetchPrint.mockResolvedValue(twoAskingSources());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/not used in Market Index/i);
    // Both raw prices, and the index between them.
    expect(screen.getByText("￥24,800")).toBeTruthy();
    expect(screen.getByText("￥20,500")).toBeTruthy();
    expect(screen.getByText("￥22,650")).toBeTruthy();
  });

  it("explains an asking price behind a keyboard- and tap-operable control", async () => {
    fetchPrint.mockResolvedValue(twoAskingSources());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    // Not a hover tooltip and not a `title` attribute: a real button, which a
    // phone can tap and a keyboard can reach. See InfoTip.
    const explain = screen.getByRole("button", { name: "About Current listing" });
    expect(explain.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(explain);

    expect(
      screen.getByText(
        "Lowest current listing observed on this source. Asking prices are not completed sales and may differ from the price a card ultimately sells for.",
      ),
    ).toBeTruthy();
  });

  it("describes evidence without colouring it as a problem", async () => {
    fetchPrint.mockResolvedValue(twoAskingSources());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    // The amber "stale"/caution vocabulary belongs to values that are actually
    // wrong or excluded. An evidence-type label is neither.
    const label = within(sources).getByText(/Current listing/);
    expect(label.className).not.toMatch(/signal-warning|amber|red/);
    expect(sources.textContent).not.toMatch(/warning|caution|unreliable/i);
  });

  it("calls a sold median a sales median, and never a listing", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 21000,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({
              source: "snkrdunk",
              reference_type: "transaction_median",
              evidence_type: "transaction",
              value_jpy: 21000,
              sample_size: 7,
              contributes_to_index: true,
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText(/Recent sales median/)).toBeTruthy();
    // The sample size still rides along with it - seven real sales is the
    // reason this is the strongest thing any source reports.
    expect(within(sources).getByText(/7 sales/)).toBeTruthy();
    expect(sources.textContent).not.toMatch(/Current listing/);
  });

  it("still says a constrained listing is out of the index", async () => {
    // v3 widened what COUNTS, not what is admissible. A platform-minimum
    // listing is still excluded and must still say so - this is the exclusion
    // communication that the "Reference only" removal must not have weakened.
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 24800,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({
              source: "yuyutei",
              value_jpy: 24800,
              contributes_to_index: true,
            }),
            sourceValue({
              source: "snkrdunk",
              value_jpy: 1000,
              eligible: false,
              fallback_used: true,
              ineligible_reason: "platform_floor",
              constraint: "platform_floor",
              contributes_to_index: false,
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("Minimum listing price")).toBeTruthy();
    expect(within(sources).getByText("Not used in Market Index")).toBeTruthy();
    // The raw number is still shown, and still labelled for what it is.
    expect(within(sources).getByText("￥1,000")).toBeTruthy();
    expect(within(sources).getByText(/Current listing/)).toBeTruthy();
  });

  it("still says a stale price is out of the index", async () => {
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 24800,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({
              source: "yuyutei",
              value_jpy: 24800,
              contributes_to_index: true,
            }),
            sourceValue({
              source: "snkrdunk",
              value_jpy: 20500,
              stale: true,
              eligible: false,
              fallback_used: true,
              ineligible_reason: "stale",
              contributes_to_index: false,
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("stale")).toBeTruthy();
    expect(within(sources).getByText("Not used in Market Index")).toBeTruthy();
  });

  it("labels a source it has never heard of with the API's own words", async () => {
    // Architecture preparation, asserted rather than asserted-to-be-intended:
    // a source and a reference type this build has no constant for still
    // render as a real, attributed price - because nothing on this page keys
    // on either name.
    fetchPrint.mockResolvedValue(
      makeDetail({
        market_index: {
          index_value_jpy: 22650,
          source_count: 2,
          coverage_status: "full",
          confidence: "high",
          source_values: [
            sourceValue({
              source: "yuyutei",
              value_jpy: 24800,
              contributes_to_index: true,
            }),
            sourceValue({
              source: "cardrush",
              reference_type: "retail_sell",
              value_jpy: 20500,
              contributes_to_index: true,
            }),
          ],
        } as PrintMarketIndex,
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("cardrush")).toBeTruthy();
    expect(within(sources).getByText("￥20,500")).toBeTruthy();
    expect(within(sources).getAllByText(/Retail price/)).toHaveLength(2);
  });
});

/** Market Index v2 made "visible" and "counted" two different things: an
 * admissible fallback source kept its price and its place in the range but
 * stood aside from the aggregate. v3 removed that role filter, so a v3 backend
 * only ever reports `contributes_to_index: false` for a value that is also
 * INELIGIBLE - constrained, stale or absent.
 *
 * The fixtures below therefore now describe two things: what the current
 * backend emits for an excluded value, and what an older v2 API's payload
 * still renders as. Both matter. The exclusion vocabulary is the one the
 * "Reference only" removal must not have weakened, and an Atlas build talking
 * to a not-yet-redeployed API must keep rendering exactly what it rendered
 * before rather than silently reinterpreting a `false` it no longer expects.
 * Every fixture is shaped on a real staging payload. */
describe("print detail page - source prices that did not feed the index", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  /** Print 5998 (OP01-005): Yuyu-Tei ¥120 counted, SNKRDUNK ¥2,500 admissible
   * but standing aside, range spanning both. */
  function withContribution(overrides: Partial<PrintMarketIndex> = {}) {
    return makeDetail({
      market_index: {
        index_value_jpy: 120,
        source_count: 1,
        coverage_status: "limited",
        confidence: "medium",
        source_price_range: { low_jpy: 120, high_jpy: 2500 },
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120, contributes_to_index: true }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 2500,
            fallback_used: true,
            contributes_to_index: false,
          }),
        ],
        ...overrides,
      } as PrintMarketIndex,
    });
  }

  it("marks the source price the index was not computed from", async () => {
    fetchPrint.mockResolvedValue(withContribution());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    expect(within(sources).getByText("Reference only")).toBeTruthy();
    expect(
      within(sources).getByText("Shown for context; not used in Market Index."),
    ).toBeTruthy();
    // The raw price is still shown in full and is still the loud thing.
    expect(within(sources).getByText("￥2,500")).toBeTruthy();
  });

  it("reconciles the index with the number of prices on screen", async () => {
    fetchPrint.mockResolvedValue(withContribution());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" }).parentElement!;
    expect(within(index).getByText("1 of 2 source prices used")).toBeTruthy();
    // Still the only figure with weight; no spread, no percentage, no warning.
    expect(within(index).getByText("￥120")).toBeTruthy();
    expect(index.textContent).not.toMatch(/%|market range|trading range|disagree/i);
  });

  // The numerator is the backend's published `source_count`. Here every row
  // claims to have contributed and a client-side tally would read "3 of 3"
  // and render nothing at all; the index says it was computed from one value,
  // and the index is the authority for its own input count.
  it("takes the numerator from source_count, not from the source rows", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        source_count: 1,
        source_price_range: null,
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120, contributes_to_index: true }),
          sourceValue({ source: "snkrdunk", value_jpy: 2500, contributes_to_index: true }),
        ],
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("1 of 2 source prices used")).toBeTruthy();
  });

  // And the mirror: source_count agrees with what is on screen, so nothing is
  // qualified however the individual rows are flagged.
  it("stays silent when source_count matches the prices on screen", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: 810,
        source_count: 2,
        source_price_range: { low_jpy: 120, high_jpy: 2500 },
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120, contributes_to_index: false }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 2500,
            fallback_used: true,
            contributes_to_index: false,
          }),
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/source prices used/);
  });

  // A SNKRDUNK-floor-only print: nothing was admissible, so there is no index
  // - and "0 of 1" is exactly what explains the visible price beneath it.
  it("states a zero count beside an unavailable index", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: null,
        source_count: 0,
        coverage_status: "none",
        confidence: "low",
        source_price_range: null,
        source_values: [
          sourceValue({
            source: "snkrdunk",
            value_jpy: 1000,
            eligible: false,
            ineligible_reason: "platform_floor",
            constraint: "platform_floor",
            contributes_to_index: false,
          }),
        ],
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("0 of 1 source prices used")).toBeTruthy();
    expect(screen.getByText("￥1,000")).toBeTruthy();
  });

  it("says the source range covers a price the index did not use", async () => {
    fetchPrint.mockResolvedValue(withContribution());
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const index = screen.getByRole("heading", { name: "Market Index" }).parentElement!;
    expect(within(index).getByText("￥120 – ￥2,500")).toBeTruthy();
    expect(
      within(index).getByText("Includes reference-only source prices."),
    ).toBeTruthy();
  });

  it("leaves the range uncaptioned when every price in it was counted", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: 810,
        source_count: 2,
        source_price_range: { low_jpy: 120, high_jpy: 1500 },
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 120, contributes_to_index: true }),
          sourceValue({ source: "snkrdunk", value_jpy: 1500, contributes_to_index: true }),
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("￥120 – ￥1,500")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Includes reference-only/);
    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/source prices used/);
  });

  /** Print 12 (OP04-001): the platform-floor price is ineligible, so it is
   * outside the range as well as outside the index. Its own, more specific
   * explanation is the right thing to read - not a second, vaguer badge. */
  it("keeps a platform-floor explanation and does not badge it twice", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: 80,
        source_price_range: null,
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 80, contributes_to_index: true }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: 1000,
            eligible: false,
            ineligible_reason: "platform_floor",
            constraint: "platform_floor",
            contributes_to_index: false,
          }),
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("Minimum listing price")).toBeTruthy();
    expect(screen.getByText("Not used in Market Index")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/Shown for context/);
    // The count still reconciles two visible prices against a one-source index.
    expect(screen.getByText("1 of 2 source prices used")).toBeTruthy();
    // No range at all, so nothing to caption.
    expect(container.textContent).not.toMatch(/Includes reference-only/);
  });

  /** Print 5997 (OP01-004): a sale price is a real, buyable price and counts.
   * SNKRDUNK reported nothing, so it has no panel and no place in any count. */
  it("leaves a counted sale price alone and ignores a source with no price", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: 80,
        source_price_range: null,
        source_values: [
          sourceValue({
            source: "yuyutei",
            value_jpy: 80,
            constraint: "sale_price",
            contributes_to_index: true,
          }),
          sourceValue({
            source: "snkrdunk",
            value_jpy: null,
            contributes_to_index: false,
          }),
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("Sale price")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/source prices used/);
  });

  /** Print 6023 (OP01-027): one source, counted, nothing to explain. */
  it("adds nothing to a print whose every price was counted", async () => {
    fetchPrint.mockResolvedValue(
      withContribution({
        index_value_jpy: 80,
        source_price_range: null,
        source_values: [
          sourceValue({ source: "yuyutei", value_jpy: 80, contributes_to_index: true }),
        ],
      }),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getAllByText("￥80").length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/source prices used/);
    expect(container.textContent).not.toMatch(/Includes reference-only/);
  });

  // The deployed API is the authority and the only input. One that predates
  // contributes_to_index sends nothing, which is not an exclusion - so no
  // panel is badged and the range gains no caption. The qualifier reads
  // source_count, which every API has always sent, and here it agrees with
  // the two prices on screen.
  it("stays safe against an API that predates contributes_to_index", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(container.textContent).not.toMatch(/Reference only/);
    expect(container.textContent).not.toMatch(/source prices used/);
    expect(container.textContent).not.toMatch(/Includes reference-only/);
    expect(screen.getAllByText("￥26,900").length).toBeGreaterThan(0);
  });

  // ...and the same old API on a print whose index counted fewer values than
  // it shows prices for still gets the qualifier, because source_count alone
  // decides it.
  it("qualifies an older API's payload from source_count alone", async () => {
    const detail = withContribution({ source_price_range: null });
    for (const sv of detail.market_index.source_values) {
      delete (sv as unknown as Record<string, unknown>).contributes_to_index;
    }
    fetchPrint.mockResolvedValue(detail);
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("1 of 2 source prices used")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Reference only/);
  });
});

/** A source that reported no price is a FACT about this print, and the panel
 * that names it is the only way the page can state that fact.
 *
 * The failure it replaces was silent by construction: a print Yuyu-Tei priced
 * and SNKRDUNK did not rendered one panel, which is byte-for-byte what a print
 * only Yuyu-Tei had ever been asked about renders. A collector comparing two
 * shops could not tell "SNKRDUNK has nothing" from "SNKRDUNK was not consulted"
 * - and the first is exactly the thing they opened the page to learn.
 *
 * These tests pin the honest version and, just as importantly, everything it
 * must NOT disturb: the constraint copy on a real price, the arithmetic above,
 * and the empty state where no source reported at all. */
describe("print detail page - a source with no price", () => {
  const UNAVAILABLE = "Price unavailable";

  function detailWithSources(
    source_values: PrintMarketIndexSourceValue[],
    index: Partial<PrintMarketIndex> = {},
  ) {
    return makeDetail({
      market_index: {
        index_value_jpy: 24000,
        source_count: 1,
        coverage_status: "limited",
        confidence: "medium",
        source_price_range: null,
        source_values,
        ...index,
      } as PrintMarketIndex,
    });
  }

  /** The panel for one named source, whatever it contains. */
  function panelFor(name: string): HTMLElement {
    const sources = screen.getByRole("heading", { name: "Market sources" }).parentElement!;
    return within(sources).getByText(name).closest(".rounded-panel") as HTMLElement;
  }

  it("names Yuyu-Tei as unavailable when only SNKRDUNK reported a price", async () => {
    fetchPrint.mockResolvedValue(
      detailWithSources([
        sourceValue({ source: "yuyutei", value_jpy: null, observed_at: null }),
        sourceValue({ source: "snkrdunk", value_jpy: 24000 }),
      ]),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(within(panelFor("SNKRDUNK")).getByText("￥24,000")).toBeTruthy();
    expect(within(panelFor("Yuyu-Tei")).getByText(UNAVAILABLE)).toBeTruthy();
  });

  it("names SNKRDUNK as unavailable when only Yuyu-Tei reported a price", async () => {
    fetchPrint.mockResolvedValue(
      detailWithSources([
        sourceValue({ source: "yuyutei", value_jpy: 29800 }),
        sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
      ]),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(within(panelFor("Yuyu-Tei")).getByText("￥29,800")).toBeTruthy();
    expect(within(panelFor("SNKRDUNK")).getByText(UNAVAILABLE)).toBeTruthy();
  });

  it("says nothing about availability when both sources reported a price", async () => {
    fetchPrint.mockResolvedValue(makeDetail());
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(within(panelFor("Yuyu-Tei")).getByText("￥29,800")).toBeTruthy();
    expect(within(panelFor("SNKRDUNK")).getByText("￥24,000")).toBeTruthy();
    expect(container.textContent).not.toMatch(UNAVAILABLE);
  });

  it("keeps the plain 'Index unavailable' empty state when no source reported", async () => {
    // One statement, not one per source. Listing every known source beneath an
    // unavailable index saying "Price unavailable" restates the same fact as
    // many times as Atlas happens to have sources.
    fetchPrint.mockResolvedValue(
      detailWithSources(
        [
          sourceValue({ source: "yuyutei", value_jpy: null, observed_at: null }),
          sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
        ],
        { index_value_jpy: null, source_count: 0, coverage_status: "none", confidence: "low" },
      ),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    expect(screen.getByText("Index unavailable")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Market sources" })).toBeNull();
    expect(container.textContent).not.toMatch(UNAVAILABLE);
  });

  it("leaves a constrained source's own copy exactly as it was", async () => {
    // The unavailable row is additive. A real price at the platform minimum
    // keeps its chip, its explanation and its "Not used in Market Index" line;
    // nothing about the new row changes what the priced panel beside it says.
    fetchPrint.mockResolvedValue(
      detailWithSources(
        [
          sourceValue({
            source: "snkrdunk",
            value_jpy: 120,
            eligible: false,
            ineligible_reason: "platform_floor",
            constraint: "platform_floor",
          }),
          sourceValue({ source: "yuyutei", value_jpy: null, observed_at: null }),
        ],
        { index_value_jpy: null, source_count: 0, coverage_status: "none", confidence: "low" },
      ),
    );
    const { container } = render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const snkrdunk = panelFor("SNKRDUNK");
    expect(within(snkrdunk).getByText("￥120")).toBeTruthy();
    expect(within(snkrdunk).getByText("Minimum listing price")).toBeTruthy();
    expect(within(snkrdunk).getByText(/Not used in Market Index/)).toBeTruthy();
    // The unavailable panel borrows none of that vocabulary: it has no price
    // to qualify, so it carries no constraint, evidence or contribution line.
    const yuyutei = panelFor("Yuyu-Tei");
    expect(within(yuyutei).getByText(UNAVAILABLE)).toBeTruthy();
    expect(yuyutei.textContent).not.toMatch(/Minimum listing price|Retail price|Reference only/);
    expect(container.textContent).not.toMatch(/platform_floor/);
  });

  it("puts no ¥0, dash or any other number where the missing price would be", async () => {
    fetchPrint.mockResolvedValue(
      detailWithSources([
        sourceValue({ source: "yuyutei", value_jpy: 29800 }),
        sourceValue({ source: "snkrdunk", value_jpy: null, observed_at: null }),
      ]),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const snkrdunk = panelFor("SNKRDUNK");
    expect(snkrdunk.textContent).toBe(`SNKRDUNK${UNAVAILABLE}`);
    // Nothing number-shaped at all: no ￥, no digit, no dash standing in for
    // one, and no "Seen <date>" for an observation that never happened.
    expect(snkrdunk.textContent).not.toMatch(/￥|\d|—|–|--|N\/A/);
  });
});
