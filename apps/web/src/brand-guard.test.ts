import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Guards the public/collector-facing surface against the old working
// names regressing back in. Deliberately source-based (not a render test)
// so it also catches strings that never make it into rendered DOM text
// (e.g. a comment, a metadata field). Internal/non-user-visible
// identifiers (the "optcg.recentWorkflows.v1" localStorage key, the
// backend's OpenAPI title, Railway service names) are intentionally out
// of scope - see docs/brand.md "Naming hierarchy" for why those remain.
const PUBLIC_COLLECTOR_FILES = [
  "app/layout.tsx",
  "app/page.tsx",
  "app/cards/page.tsx",
  "app/cards/[id]/page.tsx",
  "app/market/movers/page.tsx",
  "app/sign-in/page.tsx",
  "app/not-found.tsx",
  "app/error.tsx",
  "app/collection/page.tsx",
  "app/collection/vault/page.tsx",
  "app/wishlist/page.tsx",
  "components/ui/TopBar.tsx",
  "components/ui/SidebarNav.tsx",
  "components/Footer.tsx",
  "lib/brand.ts",
];

const FORBIDDEN = [/OPTCG Vault/i, /TCG Vault/i, /OPTCG Price Tracker/i, /\bPrice Tracker\b/i];

describe("brand guard - old working names", () => {
  it.each(PUBLIC_COLLECTOR_FILES)("%s contains no old product branding", (relativePath) => {
    const source = readFileSync(path.resolve(__dirname, relativePath), "utf-8");
    for (const pattern of FORBIDDEN) {
      expect(source).not.toMatch(pattern);
    }
  });
});
