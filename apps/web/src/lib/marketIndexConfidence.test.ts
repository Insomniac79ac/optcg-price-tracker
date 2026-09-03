/** GUARD: Market Index `confidence` must not reach a collector.
 *
 * The API publishes `market_index.confidence` as "high" | "medium" | "low".
 * The word is doing work the computation does not support: the backend derives
 * it from ONE input - the number of contributing source values - which makes
 * it a strict 1:1 relabelling of `coverage_status` and says nothing whatsoever
 * about whether the sources agree. Two eligible sources 20x apart and two
 * reporting the identical yen figure both score "high". (The contract is
 * spelled out on app.schemas.MarketIndexOut.confidence and pinned by
 * services/api/tests/test_market_index.py's
 * test_confidence_is_contributor_count_metadata_and_range_is_independent.)
 *
 * Under Market Index v3 that gap widened: an eligible current listing now
 * contributes, so "2 sources / full / high" can describe two asking prices an
 * order of magnitude apart. Rendering "High confidence" beside such a price
 * would be a reliability claim this product cannot support.
 *
 * No collector-facing surface reads the field today - but only because three
 * separate omissions happen to line up (MarketIndexValue's `Pick` leaves it
 * out, PrintUiModel carries it unread, and the tiles pass showCoverage={false}).
 * That is an accident, and this file is what turns it into a contract.
 *
 * NOT THE ADMIN VOCABULARY. `@/components/ui/ConfidenceBadge` grades
 * source-mapping matches (exact/high/medium/low/very_low/unknown) on the admin
 * surface and is unrelated to Market Index. Nothing here constrains it, and
 * the scan below deliberately never looks under src/app/admin.
 *
 * If a future tranche genuinely needs to qualify the index on screen, the
 * field to read is `source_price_range` - the one that actually measures
 * source disagreement - not this one.
 */

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Comments are prose and may discuss `confidence` freely - several of these
 * files explain exactly why they don't read it. Only code counts. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** Every collector-facing source file: all of src/app and src/components,
 * minus the admin surface, the server route handlers, and tests.
 *
 * Enumerated from disk rather than listed by hand so a NEW collector-facing
 * component is covered the day it is written, which is the only way a guard
 * like this survives contact with a future tranche. */
function collectorFacingFiles(): string[] {
  const roots = ["src/app", "src/components"];
  const files: string[] = [];

  for (const root of roots) {
    const base = resolve(process.cwd(), root);
    for (const entry of readdirSync(base, { recursive: true, encoding: "utf8" })) {
      const rel = `${root}/${entry}`.replace(/\\/g, "/");
      if (!/\.(ts|tsx)$/.test(rel)) continue;
      if (/\.test\.tsx?$/.test(rel)) continue;
      // The admin surface has its own, unrelated confidence vocabulary.
      if (rel.startsWith("src/app/admin/")) continue;
      // Route handlers proxy the API; they render nothing to a collector.
      if (rel.startsWith("src/app/api/")) continue;
      files.push(rel);
    }
  }
  return files;
}

function read(rel: string): string {
  return stripComments(readFileSync(resolve(process.cwd(), rel), "utf8"));
}

/** A read of a Market Index payload's `confidence`, in the shapes it could
 * plausibly take: a property access off an index-ish identifier, or a
 * destructure out of one. */
const CONFIDENCE_ACCESS =
  /\b(marketIndex|market_index|index|idx|print|printIndex)\s*(\?\.|\.)\s*confidence\b/;
const CONFIDENCE_DESTRUCTURE =
  /\{[^}]*\bconfidence\b[^}]*\}\s*=\s*[^;\n]*\b(marketIndex|market_index|index|print)\b/;

describe("D. Market Index confidence is never consumed by a collector-facing surface", () => {
  it("finds the collector-facing files to scan", () => {
    // A scan that silently matched nothing would pass forever and prove
    // nothing, so the enumeration itself is asserted.
    const files = collectorFacingFiles();
    expect(files.length).toBeGreaterThan(20);
    expect(files).toContain("src/app/cards/page.tsx");
    expect(files).toContain("src/app/prints/[id]/page.tsx");
    expect(files).toContain("src/components/ui/PrintCardTile.tsx");
    expect(files).toContain("src/components/ui/MarketIndexValue.tsx");
  });

  it("reads confidence off a Market Index nowhere in src/app or src/components", () => {
    const offenders = collectorFacingFiles().filter((rel) => {
      const source = read(rel);
      return CONFIDENCE_ACCESS.test(source) || CONFIDENCE_DESTRUCTURE.test(source);
    });

    expect(offenders).toEqual([]);
  });

  it("mentions confidence nowhere in any file that touches a Market Index", () => {
    // Stricter than the access test and self-extending: the moment a file
    // starts referring to a Market Index at all, it may not carry the token.
    // This is what catches a `const c = someIndex; ... c.confidence` that the
    // regexes above would miss.
    const touchesMarketIndex = collectorFacingFiles().filter((rel) =>
      /\bmarket_?[Ii]ndex\b/i.test(read(rel)),
    );
    expect(touchesMarketIndex.length).toBeGreaterThan(3);

    for (const rel of touchesMarketIndex) {
      expect(read(rel), `${rel} must not read Market Index confidence`).not.toMatch(
        /\bconfidence\b/,
      );
    }
  });

  it("keeps confidence out of the two pages this guard exists for", () => {
    // /cards and /prints/[id] named explicitly, because they are the surfaces
    // the requirement is about and neither should ever fall out of the scan
    // through a refactor that renames a directory.
    for (const rel of ["src/app/cards/page.tsx", "src/app/prints/[id]/page.tsx"]) {
      expect(read(rel), `${rel}`).not.toMatch(/\bconfidence\b/);
    }
  });

  it("omits confidence from the shared price component's own contract", () => {
    // MarketIndexValue is the one component every collector-facing Market
    // Index price flows through, and its `MarketIndexDisplay` Pick<> is the
    // structural gate: a field absent from the Pick cannot be rendered by it
    // whatever a caller passes. Asserting the Pick, not just the file, means a
    // future edit has to widen the type deliberately.
    const source = read("src/components/ui/MarketIndexValue.tsx");
    const pick = source.match(/MarketIndexDisplay\s*=\s*Pick<[\s\S]*?>;/)?.[0];

    expect(pick).toBeTruthy();
    expect(pick).not.toMatch(/confidence/);
    // The fields it does render, so a silent narrowing is caught too.
    expect(pick).toMatch(/index_value_jpy/);
    expect(pick).toMatch(/coverage_status/);
  });

  it("carries confidence through the model layer without ever reading it", () => {
    // src/lib/prints.ts is deliberately outside the scan: it mirrors the API
    // payload, so it declares the field and copies it onto PrintUiModel, and
    // that is legitimate. What it must never do is act on it - no comparison,
    // no branch, no formatting - because a decision taken there would reach
    // every surface at once.
    const source = read("src/lib/prints.ts");

    expect(source).toMatch(/confidence: index\.confidence/);
    expect(source).not.toMatch(/confidence\s*[=!]==?/);
    expect(source).not.toMatch(/if\s*\([^)]*confidence/);
    expect(source).not.toMatch(/confidence\s*\?/);
    expect(source).not.toMatch(/\$\{[^}]*confidence/);
  });
});
