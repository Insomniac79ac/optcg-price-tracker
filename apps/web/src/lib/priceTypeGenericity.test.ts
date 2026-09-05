/** A guard, not a behaviour test: it reads the Analytics 0C collector-facing
 * source and fails if a stored price-type vocabulary ever reappears in it.
 *
 * WHAT IT PROTECTS. `price_observations.price_type` is STORAGE identity in a
 * collector's own spelling - SNKRDUNK writes "floor", Yuyu-Tei writes "sell" -
 * and it carries no meaning a client is entitled to decode. The public
 * vocabulary is `reference_type`/`evidence_type`, resolved server-side by
 * app.services.source_instruments and sent on every observation, segment and
 * source value. A rule like
 *
 *     floor => listing_floor       sell  => retail_sell
 *     sold  => transaction_median  buy   => dealer_buy
 *
 * in the browser is a SECOND naming authority. It works exactly as long as
 * both sides happen to agree, and the day a Card Rush / Mercado / Cardmarket
 * source ships with its own stored spelling it silently mislabels or silently
 * drops it - which is precisely the class of bug the server-resolved fields
 * were added to make impossible. One such table did exist here and was
 * removed; this test is what stops it coming back by habit.
 *
 * WHY IT SCANS SOURCE. The equivalent behavioural assertion - "an unknown
 * instrument still charts and still labels correctly" - lives in
 * printPriceHistory.test.ts and printSeries.test.ts and is the primary
 * protection. But a mapping table only misbehaves for tokens a test happens
 * to name, so a behavioural test can never prove ABSENCE. Reading the shipped
 * source can, and the cost is one grep.
 *
 * WHAT IT DELIBERATELY IS NOT. It is not an allowlist of valid price types -
 * no such list exists anywhere in this app, and adding one would be the same
 * mistake wearing a different hat, because it would decide client-side which
 * server tokens are real. It only asserts that certain STRINGS are absent
 * from executable code.
 *
 * THE ONE EXEMPTION is @/lib/sourceEvidence, the central presentation-copy
 * module. Collector-facing words for a `reference_type` have to live
 * somewhere, and that module is the single place they do - keyed on the
 * SERVER's vocabulary, never on a stored one, which is why it is exempt from
 * the reference-type check below and still bound by the stored-token check.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(LIB_DIR, "..");

/** Every file the Analytics 0C collector-facing path executes: the two view
 * models, the section component, and the page that mounts it. */
const AUDITED = [
  "lib/printPriceHistory.ts",
  "lib/printSeries.ts",
  "components/ui/PrintPriceHistory.tsx",
  "app/prints/[id]/page.tsx",
];

/** The central presentation-copy module - audited for stored tokens like the
 * rest, exempt from the reference-type check because naming reference types
 * is its entire job. */
const COPY_MODULE = "lib/sourceEvidence.ts";

/** Stored `price_type` spellings that exist in Atlas today. A future source
 * will add more, and this list does not need to grow for the guard to keep
 * working: these are the four a developer might reach for from memory, and
 * the module docstrings say why none of them may appear. */
const STORED_PRICE_TYPE_TOKENS = ["floor", "sell", "sold", "buy"];

/** The API-facing instrument names. Legitimate everywhere the SERVER's own
 * word is being rendered - but a chart-selection or segmentation file that
 * spells one out is almost certainly deciding something about it, which is
 * the server's job. */
const REFERENCE_TYPE_TOKENS = [
  "listing_floor",
  "retail_sell",
  "transaction_median",
  "dealer_buy",
];

function read(relativePath: string): string {
  return readFileSync(join(SRC_DIR, relativePath), "utf8");
}

/** Executable code only. Comments are where these tokens SHOULD appear - the
 * modules explain at length which vocabulary is which and why - so a guard
 * that read them would forbid the documentation of its own rule. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

/** Every string and template-literal chunk in the code, which is the only
 * form a token like "floor" can take: these are data values compared against
 * an API field, never identifiers. */
function stringLiterals(source: string): string[] {
  const matches = stripComments(source).matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g);
  return [...matches].map((match) => match[1] ?? match[2] ?? match[3] ?? "");
}

function literalsMentioning(source: string, token: string): string[] {
  const pattern = new RegExp(`(^|[^A-Za-z0-9_])${token}([^A-Za-z0-9_]|$)`);
  return stringLiterals(source).filter((literal) => pattern.test(literal));
}

describe("Analytics 0C never decodes a stored price_type", () => {
  it.each(AUDITED)("%s spells no stored price-type token", (relativePath) => {
    const source = read(relativePath);
    for (const token of STORED_PRICE_TYPE_TOKENS) {
      expect(literalsMentioning(source, token), `${relativePath} mentions "${token}"`).toEqual([]);
    }
  });

  it.each([...AUDITED, COPY_MODULE])("%s never compares a price_type", (relativePath) => {
    const code = stripComments(read(relativePath));
    // A stored type may be grouped on and keyed by - equality between two
    // API-supplied values - but never tested against a literal this build
    // chose, which is what a semantic rule looks like in every form it takes:
    // an if, a switch, an includes, or a lookup table's key.
    expect(code).not.toMatch(/price_?[Tt]ype\s*[=!]==?\s*["'`]/);
    expect(code).not.toMatch(/["'`]\s*[=!]==?\s*price_?[Tt]ype\b/);
    expect(code).not.toMatch(/\[\s*[A-Za-z0-9_.]*price_?[Tt]ype\s*\]/);
    expect(code).not.toMatch(/switch\s*\(\s*[A-Za-z0-9_.]*price_?[Tt]ype/i);
  });

  it.each(AUDITED)("%s leaves reference-type copy to sourceEvidence", (relativePath) => {
    const source = read(relativePath);
    for (const token of REFERENCE_TYPE_TOKENS) {
      expect(literalsMentioning(source, token), `${relativePath} mentions "${token}"`).toEqual([]);
    }
  });

  it("keeps the reference-type vocabulary in exactly one module", () => {
    // The exemption is real and is being used - if this ever failed, the copy
    // module had been emptied and the words had gone somewhere else.
    const copy = read(COPY_MODULE);
    for (const token of REFERENCE_TYPE_TOKENS) {
      expect(copy).toContain(token);
    }
  });

  it("has no allowlist of valid price types anywhere in the audited path", () => {
    // The opposite failure mode: not "the client decodes a token" but "the
    // client decides which tokens are allowed to exist". Both make a future
    // server-defined type a frontend release.
    for (const relativePath of [...AUDITED, COPY_MODULE]) {
      const code = stripComments(read(relativePath));
      expect(code, relativePath).not.toMatch(
        /(VALID|ALLOWED|KNOWN|SUPPORTED)_(PRICE_TYPES|REFERENCE_TYPES)/,
      );
    }
  });
});
