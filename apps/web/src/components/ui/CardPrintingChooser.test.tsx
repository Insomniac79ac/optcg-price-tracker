/** What the Printings chooser is allowed to say, and what it must never do.
 *
 * The load-bearing claims here are negative: it must not merge printings, must
 * not compute a price, and must not pick a printing for the reader. Each tile
 * is the catalogue's own `PrintCardTile`, so the artwork contract and the
 * Market Index rendering are asserted through it rather than re-implemented.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardPrintingChooser } from "./CardPrintingChooser";
import {
  resolveCanonicalPrintIdentity,
  toPrintUiModel,
  type PrintCatalogueItem,
  type PrintMarketIndex,
} from "@/lib/prints";

function marketIndex(overrides: Partial<PrintMarketIndex> = {}): PrintMarketIndex {
  return {
    card_print_id: 1,
    index_version: 1,
    index_value_jpy: 6712,
    calculation_method: "midpoint",
    source_count: 2,
    coverage_status: "full",
    confidence: "high",
    source_values: [],
    auxiliary_values: [],
    freshest_observation_at: "2026-08-31T00:00:00Z",
    stalest_eligible_source_at: null,
    stale_sources: [],
    calculated_at: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

function catalogueItem(overrides: Partial<PrintCatalogueItem> = {}): PrintCatalogueItem {
  return {
    card_print_id: 11,
    canonical_card_id: 9,
    card_code: "OP04-001",
    name_en: "Nefeltari Vivi",
    name_jp: "ネフェルタリ・ビビ",
    rarity: "L",
    canonical_rarity: "L",
    card_type: "Leader",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-04",
    original_set_code: "OP-04",
    official_asset_variant: "p1",
    image_url: "https://example.test/op04-001_p1.png",
    display_image: null,
    verification_status: "verified",
    market_index: marketIndex(),
    source_coverage: ["yuyutei", "snkrdunk"],
    latest_observation_at: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

const BASE = catalogueItem({
  card_print_id: 12,
  treatment: "normal",
  official_asset_variant: "base",
  image_url: "https://example.test/op04-001_base.png",
  market_index: marketIndex({ card_print_id: 12, index_value_jpy: 80 }),
});
const PARALLEL = catalogueItem();

/** Renders exactly as the page does: identity resolved from the same records
 * the tiles are built from, never from a legacy card row. */
function renderChooser(items: PrintCatalogueItem[], status: "loading" | "error" | "ready" = "ready") {
  return render(
    <CardPrintingChooser
      status={status}
      prints={items.map(toPrintUiModel)}
      cardCode={items[0]?.card_code ?? "OP04-001"}
      canonicalName={resolveCanonicalPrintIdentity(items)?.name ?? null}
    />,
  );
}

describe("CardPrintingChooser", () => {
  it("B. renders two sibling printings as two separate options", () => {
    renderChooser([BASE, PARALLEL]);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    // Two distinct collectibles, never collapsed into one row.
    expect(new Set(links.map((l) => l.getAttribute("href"))).size).toBe(2);
  });

  it("C. links each option to its own /prints/{card_print_id}", () => {
    renderChooser([BASE, PARALLEL]);

    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/prints/12");
    expect(hrefs).toContain("/prints/11");
    // Never the legacy card route, and never a canonical id.
    expect(hrefs.some((h) => h?.startsWith("/cards/"))).toBe(false);
    expect(hrefs).not.toContain("/prints/9");
  });

  it("D. renders a one-printing card as an option rather than choosing for the reader", () => {
    renderChooser([BASE]);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/prints/12");
    // The section still states itself - a single printing is information,
    // not a reason to redirect.
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Printings of Nefeltari Vivi OP04-001",
    );
  });

  it("E. survives a printing whose Market Index is unavailable", () => {
    const unpriced = catalogueItem({
      card_print_id: 2885,
      treatment: null,
      official_asset_variant: null,
      market_index: marketIndex({
        card_print_id: 2885,
        index_value_jpy: null,
        source_count: 0,
        coverage_status: "none",
        confidence: "low",
      }),
      source_coverage: [],
      latest_observation_at: null,
    });

    renderChooser([BASE, unpriced]);

    expect(screen.getAllByRole("link")).toHaveLength(2);
    // The catalogue's own honest wording, not ¥0 and not a borrowed sibling
    // price.
    expect(screen.getByText(/Index unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("￥0")).not.toBeInTheDocument();
  });

  it("F. reconstructs no card-level history and no sibling price", () => {
    const { container } = renderChooser([BASE, PARALLEL]);

    // Each tile shows only its OWN index. ¥80 and ¥6,712 both appear; no
    // third, merged or averaged figure exists anywhere.
    expect(screen.getByText("￥80")).toBeInTheDocument();
    expect(screen.getByText("￥6,712")).toBeInTheDocument();
    const yenFigures = (container.textContent ?? "").match(/￥[\d,]+/g) ?? [];
    expect(yenFigures.sort()).toEqual(["￥6,712", "￥80"]);
    // No chart, no series, no observation table on a navigation surface.
    expect(container.querySelector("svg.recharts-surface")).toBeNull();
    expect(container.querySelector("table")).toBeNull();
  });

  it("H. shows full uncropped artwork through the shared image frame", () => {
    const { container } = renderChooser([BASE, PARALLEL]);

    const imgs = [...container.querySelectorAll("img")];
    expect(imgs.length).toBeGreaterThanOrEqual(2);
    for (const img of imgs) {
      // The no-crop contract: contain-fit, never cover, never a background
      // crop or a mask.
      expect(img.className).toContain("object-contain");
      expect(img.className).not.toContain("object-cover");
    }
  });

  it("distinguishes base from parallel so the reader can tell them apart", () => {
    renderChooser([BASE, PARALLEL]);

    const links = screen.getAllByRole("link");
    const labels = links.map((l) => l.getAttribute("aria-label") ?? "");
    // The two options must not read identically.
    expect(new Set(labels).size).toBe(2);
    expect(labels.some((l) => /alt art/i.test(l))).toBe(true);
  });

  it("shows a skeleton while loading and never an empty claim", () => {
    const { container } = renderChooser([], "loading");

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Printings of");
    expect(screen.queryByText(/No printings/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("a")).toHaveLength(0);
  });

  it("says so plainly when the printings cannot be loaded", () => {
    renderChooser([], "error");
    expect(screen.getByText(/couldn’t be loaded right now/)).toBeInTheDocument();
  });

  it("says so plainly when the card has no catalogued printings", () => {
    renderChooser([], "ready");
    expect(screen.getByText(/No printings of this card have been catalogued yet/))
      .toBeInTheDocument();
  });

  it("keeps each tile's identifying detail on its own tile", () => {
    renderChooser([BASE, PARALLEL]);

    for (const link of screen.getAllByRole("link")) {
      expect(within(link).getByText("OP04-001")).toBeInTheDocument();
    }
  });
});

describe("CardPrintingChooser identity", () => {
  it("heads the set with the canonical name when every record agrees", () => {
    renderChooser([BASE, PARALLEL]);

    expect(
      screen.getByRole("heading", { name: /Printings of Nefeltari Vivi OP04-001/ }),
    ).toBeInTheDocument();
  });

  it("falls back to the card code when the records disagree on a name", () => {
    // Two spellings is a disagreement, not a tie to break.
    const other = catalogueItem({ card_print_id: 77, name_en: "Nefertari Vivi" });
    renderChooser([BASE, other]);

    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("Printings of OP04-001");
    expect(heading).not.toHaveTextContent("Nefeltari Vivi");
    expect(heading).not.toHaveTextContent("Nefertari Vivi");
    // The printings themselves still render - only the name is withheld.
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("falls back to the card code when the records span two canonical cards", () => {
    const foreign = catalogueItem({ card_print_id: 88, canonical_card_id: 999 });
    renderChooser([BASE, foreign]);

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Printings of OP04-001",
    );
  });

  it("shows the code alone while still loading, never a guessed name", () => {
    render(
      <CardPrintingChooser status="loading" prints={[]} cardCode="OP04-001" canonicalName={null} />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Printings of OP04-001",
    );
  });
});
