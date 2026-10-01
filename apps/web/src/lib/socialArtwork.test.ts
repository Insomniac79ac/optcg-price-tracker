// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { artworkData } from "./socialArtwork";
afterEach(() => vi.unstubAllGlobals());
it("never fetches unapproved, HTTP, deceptive or authenticated artwork URLs", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  for (const url of ["http://www.onepiece-cardgame.com/card.png", "https://www.onepiece-cardgame.com.evil.test/card.png", "https://user:pass@www.onepiece-cardgame.com/card.png", "file:///etc/passwd"]) expect(await artworkData(url)).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});
it("rejects non-image and oversized declared bodies and prohibits redirects", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("no image", { headers: { "content-type": "text/html" } })); vi.stubGlobal("fetch", fetcher);
  expect(await artworkData("https://www.onepiece-cardgame.com/card.png")).toBeNull();
  expect(fetcher).toHaveBeenCalledWith(expect.any(URL), expect.objectContaining({ redirect: "error" }));
  fetcher.mockResolvedValue(new Response("", { headers: { "content-type": "image/png", "content-length": "8000001" } }));
  expect(await artworkData("https://www.onepiece-cardgame.com/card.png")).toBeNull();
});
