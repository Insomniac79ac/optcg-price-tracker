import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ShareCard } from "./shareCard";
import { marketShareContent, printShareContent, socialFaction, publicArtwork } from "./shareContent";
import { printFixture } from "./publicDiscoveryFixtures";
import fixtures from "./__fixtures__/marketValue.json";
import type { PrintDetail } from "./prints";
const detail = { ...printFixture(1), name_en: "Monkey.D.Luffy", card_code: "OP05-119", colors: null, artwork_key: null, siblings: [] } as PrintDetail;
describe("dynamic proof content", () => {
  it("uses exact canonical identities for faction frames, not names or code prefixes alone", () => {
    expect(socialFaction(detail).theme).toBe("straw-hat");
    expect(socialFaction({ ...detail, card_code: "OP01-025", name_en: "Roronoa Zoro" }).theme).toBe("straw-hat");
    expect(socialFaction({ ...detail, card_code: "OP02-099", name_en: "Sakazuki" }).theme).toBe("marine");
    expect(socialFaction({ ...detail, name_en: "Luffy & Ace" }).theme).toBe("neutral");
    expect(socialFaction({ ...detail, card_code: "ST01-010", name_en: "Franky" }).theme).toBe("neutral");
  });
  it("rejects non-exact display art while keeping canonical artwork", () => {
    expect(publicArtwork({ ...detail, display_image: { url: "wrong.png", exact_print_verified: false, source: "yuyutei", geometry: null } })).toBe(detail.image_url);
    expect(publicArtwork({ ...detail, display_image: { url: "exact.png", exact_print_verified: true, source: "yuyutei", geometry: null } })).toBe("exact.png");
  });
  it("omits unavailable/withheld movement and does not replace it with zero", () => {
    for (const movement of [{ ...fixtures.overall.movement, available: false }, { ...fixtures.overall.movement, pct: null }, { ...fixtures.overall.movement, pct: "NaN" }, { ...fixtures.overall.movement, reason: "insufficient_window_continuity" }]) {
      expect(marketShareContent({ ...fixtures.overall, movement } as Parameters<typeof marketShareContent>[0]).movement).toBeUndefined();
    }
  });
  it("does not show movement for a different requested window", () => {
    expect(marketShareContent(fixtures.overall as Parameters<typeof marketShareContent>[0], "30d").movement).toBeUndefined();
  });
  it("renders production copy and dynamic values without proof samples or internal terminology", () => {
    const content = printShareContent({ ...detail, official_asset_variant: "base", market_index: { ...detail.market_index, index_value_jpy: 87654 } });
    const html = renderToStaticMarkup(<ShareCard content={content} />);
    expect(html).toContain("¥87,654"); expect(html).toContain("Regular art"); expect(html).toContain("Card Pirate");
    expect(html).not.toMatch(/SAMPLE DATA|DESIGN PREVIEW|CardPirate Atlas|\bprinting\b|\bprint\b/i);
    expect(html).toContain("WANTED");
    const neutral = renderToStaticMarkup(<ShareCard content={{ ...content, theme: "neutral" }} />);
    expect(neutral).not.toContain("WANTED");
  });
});
