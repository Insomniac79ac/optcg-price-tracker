// @vitest-environment node
import { describe, expect, it, vi, beforeEach } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/publicServer", () => ({ readCatalogue: vi.fn(), readMarket: vi.fn(), readPrint: vi.fn(), readReleases: vi.fn() }));
vi.mock("@/lib/socialArtwork", () => ({ artworkData: vi.fn(async () => null) }));
import { readCatalogue, readMarket, readPrint } from "@/lib/publicServer";
import { artworkData } from "@/lib/socialArtwork";
import { catalogueFixture, printFixture } from "@/lib/publicDiscoveryFixtures";
import fixtures from "@/lib/__fixtures__/marketValue.json";
import type { MarketValue } from "@/lib/marketValue";
import { GET } from "./route";
const get = (kind: string, id: string, query = "") => GET(new Request(`http://localhost/share/${kind}/${id}${query}`), { params: Promise.resolve({ kind, id }) });
beforeEach(() => { vi.clearAllMocks(); vi.mocked(readCatalogue).mockResolvedValue(catalogueFixture([])); });
describe("dynamic social routes", () => {
  it("rejects arbitrary scopes, unsafe identifiers and unsupported windows", async () => {
    expect((await get("collection", "1")).status).toBe(404);
    expect((await get("print", "9007199254740992")).status).toBe(404);
    expect((await get("market", "overall", "?window=1h")).status).toBe(400);
    expect(readPrint).not.toHaveBeenCalled();
  });
  it("renders a valid 1200x630 home PNG when artwork is unavailable", async () => {
    const res = await get("home", "site");
    const png = Buffer.from(await res.arrayBuffer());
    expect(res.headers.get("content-type")).toContain("image/png");
    expect(png.readUInt32BE(16)).toBe(1200); expect(png.readUInt32BE(20)).toBe(630);
  });
  it("renders exact and market templates through the image engine", async () => {
    vi.mocked(readPrint).mockResolvedValue({ ...printFixture(1), colors: null, artwork_key: null, siblings: [] });
    vi.mocked(readMarket).mockResolvedValue(fixtures.overall as MarketValue);
    for (const [kind, id] of [["print", "1"], ["market", "overall"]]) {
      const png = Buffer.from(await (await get(kind, id)).arrayBuffer());
      expect(png.readUInt32BE(16)).toBe(1200); expect(png.readUInt32BE(20)).toBe(630);
    }
  });
  it("requests selected-window data and excludes foreign release artwork", async () => {
    vi.mocked(readMarket).mockResolvedValue(fixtures.eligible as MarketValue);
    const own = printFixture(1, { release_product_id: 181 });
    vi.mocked(readCatalogue).mockResolvedValue(catalogueFixture([own, printFixture(2, { release_product_id: 999 })]));
    const res = await get("release", "181", "?window=30d");
    await res.arrayBuffer();
    expect(readMarket).toHaveBeenCalledWith(181, "30d");
    expect(readCatalogue).toHaveBeenCalledWith(expect.stringContaining("release_product_id=181"));
    expect(artworkData).toHaveBeenCalledTimes(1); expect(artworkData).toHaveBeenCalledWith(own.image_url);
  });
});
