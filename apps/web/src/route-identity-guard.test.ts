import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** Guards the card-print identity boundary at the routing layer.
 *
 * The product is print-centric: /prints/{card_print_id} is a claim about one
 * exact printing, while /cards/{cards.id} is a claim about a canonical card
 * that may have several printings. The two ids live in *different
 * namespaces* - in staging, card code OP01-001 is legacy `cards.id` 1 and 11
 * but its print's `canonical_card_id` is 2 - so substituting one for the
 * other does not fail loudly, it silently routes a collector to a different
 * card's printing.
 *
 * Source-based rather than a render test on purpose: this has to catch a bad
 * template literal anywhere in the app, including on routes that have no test
 * of their own, and it has to keep catching it as pages are added.
 */
const SRC_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)));

/** Every non-test .ts/.tsx under src/, walked explicitly rather than via
 * fs.globSync so this needs nothing newer than the installed @types/node. */
function productionSourceFiles(dir: string = SRC_ROOT): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      out.push(...productionSourceFiles(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry.name)) continue;
    if (/\.test\.tsx?$/.test(entry.name)) continue;
    out.push(full);
  }
  return out;
}

/** Every `/prints/${expr}` in an href/route position, with the expression. */
const PRINT_ROUTE = /["'`]\/prints\/\$\{([^}]+)\}/g;
/** Every `/cards/${expr}` in an href/route position, with the expression.
 * Restricted to link/route construction - `apiGet("/cards/${id}")` calls the
 * card-level API and is a different, legitimate thing. */
const CARD_ROUTE = /href=\{`\/cards\/\$\{([^}]+)\}/g;

/** Identifiers that genuinely denote one exact printing. */
const PRINT_ID_EXPRESSION = /(card_print_id|cardPrintId|printId)/;
/** Identifiers that denote a canonical/legacy card, never a printing. */
const CARD_ID_EXPRESSION = /(card_id|cardId|\bcard\.id\b|canonical_card_id|canonicalCardId)/;

function matchesIn(source: string, pattern: RegExp): string[] {
  return [...source.matchAll(new RegExp(pattern))].map((m) => m[1].trim());
}

describe("route identity: card vs print", () => {
  const files = productionSourceFiles();

  it("finds production source to scan", () => {
    // Guards the guard: a broken glob would make every assertion below pass
    // vacuously.
    expect(files.length).toBeGreaterThan(50);
  });

  it("builds every /prints/ route from a print id, never a card id", () => {
    const offenders: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf-8");
      for (const expr of matchesIn(source, PRINT_ROUTE)) {
        const rel = path.relative(SRC_ROOT, file);
        if (!PRINT_ID_EXPRESSION.test(expr)) {
          offenders.push(`${rel}: /prints/\${${expr}} is not built from a print id`);
        }
        if (CARD_ID_EXPRESSION.test(expr)) {
          offenders.push(`${rel}: /prints/\${${expr}} is built from a CARD id`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it("builds every /cards/ link from a card id, never a print id", () => {
    const offenders: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf-8");
      for (const expr of matchesIn(source, CARD_ROUTE)) {
        if (PRINT_ID_EXPRESSION.test(expr)) {
          offenders.push(
            `${path.relative(SRC_ROOT, file)}: /cards/\${${expr}} is built from a PRINT id`,
          );
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it("routes the one collector tile by card_print_id", () => {
    const printTile = readFileSync(path.join(SRC_ROOT, "components/ui/PrintCardTile.tsx"), "utf-8");
    expect(printTile).toMatch(/href=\{`\/prints\/\$\{print\.cardPrintId\}`\}/);
  });

  it("keeps every public collector surface off the legacy canonical catalogue", () => {
    // Discover and the Market Index page both migrated to `GET /prints`.
    // fetchCardsCatalogue carries no print identity, so a public surface
    // reading it again could not link to an exact printing without guessing.
    const publicSurfaces = ["app/page.tsx", "app/market/movers/page.tsx", "app/cards/page.tsx"];
    const offenders = publicSurfaces.filter((rel) =>
      /fetchCardsCatalogue/.test(readFileSync(path.join(SRC_ROOT, rel), "utf-8")),
    );

    expect(offenders).toEqual([]);
  });

  it("has no second, canonical-card collector tile to drift from", () => {
    // CollectorCardTile was retired with that migration. If it ever comes
    // back it must arrive with its own routing rules, not silently inherit
    // a print route.
    expect(existsSync(path.join(SRC_ROOT, "components/ui/CollectorCardTile.tsx"))).toBe(false);
  });

  it("never reads canonical_card_id into a rendered route", () => {
    // canonical_card_id is a THIRD namespace (it keys `canonical_cards`, not
    // `cards` and not `card_prints`). It is carried in the print payload types
    // but must never reach a URL.
    const offenders = files.filter((file) => {
      const source = readFileSync(file, "utf-8");
      return /href=\{`[^`]*\$\{[^}]*canonical_card_id/.test(source);
    });

    expect(offenders.map((f) => path.relative(SRC_ROOT, f))).toEqual([]);
  });
});
