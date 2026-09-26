import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet } from "./api";
import { fetchMarketOverview } from "./marketAnalytics";
import { printFixture } from "./publicDiscoveryFixtures";
vi.mock("./api", () => ({apiGet:vi.fn()}));
beforeEach(()=>vi.mocked(apiGet).mockReset());

describe("Market overview authoritative wire contract",()=>{
  it("sends release_product_id, rarity and basis without set or client-side membership filtering",async()=>{
    // Existing mixed-code OP-17 regression: EB04-007 physically belongs to
    // product 186, despite its printed code and denormalized legacy EB-04.
    const mixed = printFixture(3686,{card_code:"EB04-007",release_product_id:186,release_product_code:"EB-04",release_code:"OP-17"});
    const server = {scope:{release_product_id:mixed.release_product_id,active_prints:3,set:null,rarity:"SEC"},coverage:{usable_priced_prints:2,coverage_pct:66.67}};
    vi.mocked(apiGet).mockResolvedValue(server);
    const result = await fetchMarketOverview({release_product_id:186,set:"EB-04",rarity:"SEC",priceBasis:"source:yuyutei"});
    expect(apiGet).toHaveBeenCalledExactlyOnceWith("/analytics/market/overview",{params:{release_product_id:186,set:undefined,rarity:"SEC",price_basis:"source:yuyutei"}});
    expect(result).toBe(server);
    expect(result.scope.active_prints).toBe(3);
    expect(result.coverage.coverage_pct).toBe(66.67);
  });
  it("retains legacy set support for callers without an explicit ID",async()=>{
    vi.mocked(apiGet).mockResolvedValue({});
    await fetchMarketOverview({set:"OP-17"});
    expect(apiGet).toHaveBeenCalledWith("/analytics/market/overview",{params:{release_product_id:undefined,set:"OP-17",rarity:undefined,price_basis:undefined}});
  });
});

describe("Market cards wire contract",()=>{
  it("requests only six neutral server-ordered prints with the complete scope",async()=>{
    const {fetchMarketCards}=await import("./marketAnalytics");
    const payload={items:[printFixture(3686,{card_code:"EB04-007",release_product_id:186,release_code:"OP-17"})]};
    vi.mocked(apiGet).mockResolvedValue(payload);
    expect(await fetchMarketCards({release_product_id:186,set:"EB-04",rarity:"SEC",priceBasis:"source:snkrdunk"})).toBe(payload);
    expect(apiGet).toHaveBeenCalledExactlyOnceWith("/prints",{params:{release_product_id:186,set:undefined,rarity:"SEC",price_basis:"source:snkrdunk",sort:"card_code_asc",limit:6}});
  });
  it("requests the same bounded neutral cohort for broad Market",async()=>{
    const {fetchMarketCards}=await import("./marketAnalytics");
    vi.mocked(apiGet).mockResolvedValue({items:[]});await fetchMarketCards({priceBasis:"market_index"});
    expect(apiGet).toHaveBeenCalledExactlyOnceWith("/prints",{params:{release_product_id:undefined,set:undefined,rarity:undefined,price_basis:"market_index",sort:"card_code_asc",limit:6}});
  });
});
