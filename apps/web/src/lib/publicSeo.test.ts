import { describe, expect, it, vi } from "vitest";
import { printIdentity, printPriceTitle, printProduct, pageMetadata, serializeJsonLd } from "./publicSeo";
import { marketShareContent, printShareContent } from "./shareContent";
import type { PrintDetail } from "./prints";
import type { MarketValue } from "./marketValue";
import fixtures from "./__fixtures__/marketValue.json";
const print = { card_print_id: 1, canonical_card_id: 2, card_code: "OP01-001", name_en: "Roronoa Zoro", name_jp: null, language: "jp", official_asset_variant: "base", release_product_id: 181, release_code: "OP-01", release_name: "ROMANCE DAWN", image_url: null, display_image: null, market_index: { index_value_jpy: null, source_count: 0, freshest_observation_at: null, calculated_at: "2099-01-01", stale_sources: [] } } as unknown as PrintDetail;
describe("public identity and sharing", () => {
  it("disambiguates two physical printings of the same card", () => {
    expect(printProduct(print).sku).not.toBe(printProduct({ ...print, card_print_id: 2 }).sku);
    expect(printIdentity(print).detail).not.toMatch(/Print \d/);
    const product = printProduct(print);
    expect(product.sku).toBe("card-print-1");
    expect(product.url).toMatch(/\/prints\/1$/);
    expect(product).not.toHaveProperty("offers");
    expect(product).not.toHaveProperty("seller");
  });
  it("escapes hostile canonical names in JSON-LD without corrupting the data", () => {
    const hostile = printProduct({ ...print, name_en: '</script><script>alert("x")</script>' });
    const json = serializeJsonLd(hostile);
    expect(json).not.toContain("</script>");
    expect(JSON.parse(json)).toEqual(hostile);
  });
  it("uses one configured origin for canonical and social URLs", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://cards.example/");
    const metadata = pageMetadata("Zoro Price", "Exact print", "/prints/1", "/share/print/1");
    expect(metadata.alternates?.canonical).toBe("https://cards.example/prints/1");
    expect(metadata.openGraph).toMatchObject({ url: "https://cards.example/prints/1", images: [{ url: "https://cards.example/share/print/1", width: 1200, height: 630, alt: "Zoro Price" }] });
    vi.unstubAllEnvs();
  });
  it("never converts a missing price to zero or calculation time to freshness", () => {
    const content = printShareContent(print);
    expect(content.value).toBe("Value unavailable");
    expect(content.date).toContain("unknown");
    expect(JSON.stringify(content)).not.toContain("2099");
  });
  it("keeps coverage adjacent to market value and respects unavailable movement", () => {
    const data = structuredClone(fixtures.overall) as MarketValue;
    data.movement.available = false;
    data.movement.pct = "0";
    expect(marketShareContent(data).movement).toBeUndefined();
    expect(marketShareContent(data).context).toContain("639 of 4,316 card variants priced");
    data.movement.available = true;
    expect(marketShareContent(data).movement).toEqual({ window: "7D", value: "0.00%" });
  });
});


describe("concise exact-print titles", () => {
  it("keeps an ordinary print title free of database identity", () => {
    expect(printPriceTitle(print)).toBe("Roronoa Zoro OP01-001 Price");
  });
  it("distinguishes base and alternate artwork using authoritative variants", () => {
    const alt = { ...print, card_print_id: 2, official_asset_variant: "p1", siblings: [print] };
    expect(printPriceTitle({ ...print, siblings: [alt] })).toBe("Roronoa Zoro OP01-001 Regular Art Price");
    expect(printPriceTitle(alt)).toBe("Roronoa Zoro OP01-001 Alt Art Price");
    expect(printPriceTitle({ ...alt, card_print_id: 3, official_asset_variant: "p2", siblings: [alt] })).toBe("Roronoa Zoro OP01-001 Art 3 Price");
  });
  it("identifies special prints without treating a reprint as original artwork", () => {
    expect(printPriceTitle({ ...print, rarity: "SPカード", official_asset_variant: "p1" })).toBe("Roronoa Zoro OP01-001 SP Card Alt Art Price");
    expect(printPriceTitle({ ...print, official_asset_variant: "r1" })).toBe("Roronoa Zoro OP01-001 Reprint Price");
  });
  it("preserves distinct canonical identities when reprints share a short title", () => {
    const reprints = [
      { ...print, card_print_id: 10, official_asset_variant: "r1", release_product_id: 190, release_code: "PRB-01" },
      { ...print, card_print_id: 11, official_asset_variant: "r2", release_product_id: 191, release_code: "PRB-02" },
    ];
    expect(printPriceTitle(reprints[0])).toBe(printPriceTitle(reprints[1]));
    expect(printIdentity(reprints[0]).detail).not.toBe(printIdentity(reprints[1]).detail);
    expect(printProduct(reprints[0]).sku).not.toBe(printProduct(reprints[1]).sku);
    expect(printProduct(reprints[0]).url).not.toBe(printProduct(reprints[1]).url);
  });
  it.each([null, "x1"])("does not invent original artwork for %s provenance", (variant) => {
    expect(printPriceTitle({ ...print, official_asset_variant: variant, treatment: "normal", siblings: [print] })).toBe("Roronoa Zoro OP01-001 Price");
  });
  it("keeps the real uncoded Franky anniversary release in identity rather than the title", () => {
    const franky = { ...print, card_print_id: 6823, card_code: "ST01-010", name_en: "Franky", official_asset_variant: "p1", release_product_id: 230, release_code: null, release_name: "プレミアムカードコレクション 25周年エディション" };
    expect(printPriceTitle(franky)).toBe("Franky ST01-010 Alt Art Price");
    expect(printIdentity(franky).detail).toContain("25th Anniversary");
    expect(printIdentity(franky).detail).not.toContain("6823");
    expect(printProduct(franky).sku).toBe("card-print-6823");
  });
  it("labels social value as an estimate with its contributing evidence", () => {
    expect(printShareContent(print).context).toBe("0 contributing sources · Japanese sources · this version");
  });
});
