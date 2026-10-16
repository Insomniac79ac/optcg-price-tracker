// @vitest-environment node
import { describe, expect, it } from "vitest";
import { GET } from "./route";
const get = (kind: string, id: string, query = "") => GET(new Request(`http://localhost/share/${kind}/${id}${query}`), { params: Promise.resolve({ kind, id }) });
describe("share image routes (static fallback)", () => {
  it("rejects arbitrary scopes, unsafe identifiers and unsupported windows", async () => {
    expect((await get("collection", "1")).status).toBe(404);
    expect((await get("print", "9007199254740992")).status).toBe(404);
    expect((await get("print", "01")).status).toBe(404);
    expect((await get("market", "overall", "?window=1h")).status).toBe(400);
  });
  it("serves the same 1200x630 PNG for every known share URL", async () => {
    const bodies: Buffer[] = [];
    for (const [kind, id] of [["home", "site"], ["print", "1"], ["release", "181"], ["market", "overall"]]) {
      const res = await get(kind, id);
      expect(res.status).toBe(200);
      expect(res.headers.get("content-type")).toBe("image/png");
      const png = Buffer.from(await res.arrayBuffer());
      expect(png.readUInt32BE(16)).toBe(1200); expect(png.readUInt32BE(20)).toBe(630);
      bodies.push(png);
    }
    expect(bodies.every((body) => body.equals(bodies[0]))).toBe(true);
  });
  it("no longer imports next/og", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("./route.tsx", import.meta.url), "utf8");
    expect(source).not.toMatch(/from "next\/og"/);
  });
});
