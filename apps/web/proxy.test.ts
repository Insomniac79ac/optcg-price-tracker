import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { PROTECTED_MATCHER } from "@/lib/proxyGuard";

// proxy.ts can't import PROTECTED_MATCHER into its `config.matcher` field -
// Next.js requires that field to be a static array literal (see the comment
// in proxy.ts). This test guards against the inlined literal drifting from
// the tested source of truth in src/lib/proxyGuard.ts by parsing proxy.ts's
// own source rather than importing it (importing it would pull in
// next-auth's `auth()` wrapper, which needs a live NextAuth config).
describe("proxy.ts config.matcher", () => {
  it("stays identical to proxyGuard.PROTECTED_MATCHER", () => {
    const source = readFileSync(join(__dirname, "proxy.ts"), "utf-8");
    const match = source.match(/matcher:\s*\[([\s\S]*?)\]/);
    expect(match).not.toBeNull();
    const entries = Array.from(match![1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
    expect(entries).toEqual(PROTECTED_MATCHER);
  });
});
