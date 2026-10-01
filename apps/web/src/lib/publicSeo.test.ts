import { describe, expect, it, vi } from "vitest";
import { printIdentity, printProduct, pageMetadata, serializeJsonLd } from "./publicSeo";
import { marketShareContent, printShareContent } from "./shareContent";
import type { PrintDetail } from "./prints";
import type { MarketValue } from "./marketValue";
import fixtures from "./__fixtures__/marketValue.json";
const print = { card_print_id: 1, canonical_card_id: 2, card_code: "OP01-001", name_en: "Roronoa Zoro", name_jp: null, language: "jp", official_asset_variant: "base", release_product_id: 181, release_code: "OP-01", release_name: "ROMANCE DAWN", image_url: null, display_image: null, market_index: { index_value_jpy: null, source_count: 0, freshest_observation_at: null, calculated_at: "2099-01-01", stale_sources: [] } } as unknown as PrintDetail;
describe("public identity and sharing", () => {
  it("disambiguates two physical printings of the same card", () => {
    expect(printIdentity(print).detail).not.toBe(printIdentity({ ...print, card_print_id: 2 }).detail);
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
    expect(marketShareContent(data).identity).toBe("Price movement unavailable");
    expect(marketShareContent(data).context).toContain("639 of 4,316 printings priced");
    data.movement.available = true;
    expect(marketShareContent(data).identity).toBe("0.00% over 7 days");
  });
});
