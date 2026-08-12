import { describe, expect, it } from "vitest";

import { isProxiedImageHost, resolveCardImageUrl } from "./cardImage";

describe("isProxiedImageHost", () => {
  it("matches the approved host exactly", () => {
    expect(isProxiedImageHost("www.onepiece-cardgame.com")).toBe(true);
  });

  it("does not match lookalike hostnames that merely contain it", () => {
    expect(isProxiedImageHost("www.onepiece-cardgame.com.evil.tld")).toBe(false);
    expect(isProxiedImageHost("evil-www.onepiece-cardgame.com.attacker.io")).toBe(false);
    expect(isProxiedImageHost("notwww.onepiece-cardgame.com")).toBe(false);
  });

  it("does not proxy hosts that embed cross-origin cleanly", () => {
    expect(isProxiedImageHost("card.yuyu-tei.jp")).toBe(false);
  });
});

describe("resolveCardImageUrl", () => {
  it("routes a CORP-restricted host through the same-origin proxy", () => {
    const resolved = resolveCardImageUrl(
      "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png?260630",
    );
    expect(resolved).toBe(
      "/api/card-image?u=" +
        encodeURIComponent(
          "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png?260630",
        ),
    );
  });

  it("leaves a cleanly-embeddable host hotlinked", () => {
    const direct = "https://card.yuyu-tei.jp/opc/front/op01/10002.jpg";
    expect(resolveCardImageUrl(direct)).toBe(direct);
  });

  it("never proxies a non-https url", () => {
    const insecure = "http://www.onepiece-cardgame.com/images/cardlist/card/OP01-013.png";
    expect(resolveCardImageUrl(insecure)).toBe(insecure);
  });

  it("passes null and malformed urls through untouched", () => {
    expect(resolveCardImageUrl(null)).toBeNull();
    expect(resolveCardImageUrl("not-a-url")).toBe("not-a-url");
  });
});
