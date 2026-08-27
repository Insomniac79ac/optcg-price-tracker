/** The one place collector-facing terminology lives.
 *
 * Backend and Bandai vocabulary - `SPカード`, `p3`, `release_product_code`,
 * `coverage_status` - must never reach a collector's eyes unexplained. This
 * module turns each raw value into a label and a short definition, so the copy
 * can be changed or translated without touching a component, and so two
 * surfaces can never drift into describing the same thing differently. It
 * follows the contract `lib/sourceConstraint.ts` already established for
 * source constraints.
 *
 * THREE DIMENSIONS, NOT ONE. Bandai publishes a single `rarity` token per
 * catalogue entry, but that token carries up to three unrelated collector
 * facts, and flattening them is what made a print read as if "SP Card" were
 * its scarcity tier:
 *
 *     Rarity         C UC R SR SEC L P      - how scarce the card is
 *     Special print  SP Card, Treasure Rare - a special printing category
 *     Printing       Alt Art, Reprint       - which printing this item is
 *
 * They are independent, so one print is legitimately all three at once:
 * Super Rare (rarity), SP Card (special print), Alt Art (printing). Rarity
 * and special print are read out of the rarity token; printing is read only
 * from `official_asset_variant`. A token that names a special print is NOT a
 * rarity, and `rarityTerm` returns null for it rather than dressing it up as
 * one - the underlying rarity, if a collector is to see one at all, has to
 * come from authoritative data (see `lib/prints.ts`), never from inference.
 *
 * THE FAIL-SAFE RULE, and why it is the important one. Every lookup returns
 * `null` for a value this build has never heard of, and every caller renders
 * either the raw source value or nothing at all. It must never invent a
 * definition: a future Bandai rarity, or an asset family beyond p/r, is
 * unrecognised evidence a human should look at - and a guessed human-friendly
 * meaning would be indistinguishable from a real one at a glance.
 *
 * WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not classify printings
 * from artwork, rarity or product; the only input to a printing type is
 * `official_asset_variant`, which is Bandai's own asset address. And it never
 * calls a p-family printing "Parallel": Bandai publishes that word on only
 * some of them - 33 of 33 p-variants on OP-01 carry it, 0 of 50 on OP-17 -
 * so it is corroborating source metadata, not a definition.
 */

export type TermCategory = "printing" | "rarity" | "special_print" | "pricing" | "identity";

export interface Term {
  /** Stable id, e.g. "printing.alt_art". Never rendered. */
  key: string;
  /** What a collector reads. */
  label: string;
  /** The dense form for a badge, where the full label is too long to sit on a
   * tile. Only set where the short form is itself published and recognised -
   * "TR" for Treasure Rare. Callers fall back to `label`. */
  shortLabel?: string;
  /** One plain sentence, understandable without prior knowledge. */
  definition: string;
  /** The raw published token, where showing it in detail/help adds provenance
   * rather than noise. Never rendered on a dense tile. */
  sourceLabel?: string;
  category: TermCategory;
}

/** `official_asset_variant` -> printing type.
 *
 * `base` is the ordinary printing and gets no badge - a label on every tile
 * would be noise, and its absence is already the signal. Anything outside the
 * two known families returns null, so an unfamiliar asset address is shown as
 * nothing rather than mislabelled. */
export function printingTypeTerm(officialAssetVariant: string | null | undefined): Term | null {
  if (!officialAssetVariant) return null;
  const variant = officialAssetVariant.trim().toLowerCase();
  if (variant === "base") return null;
  if (/^p\d+$/.test(variant)) {
    return {
      key: "printing.alt_art",
      label: "Alt Art",
      definition: "Another official artwork of the same card.",
      category: "printing",
    };
  }
  if (/^r\d+$/.test(variant)) {
    return {
      key: "printing.reprint",
      label: "Reprint",
      definition: "A printing released again in another product.",
      category: "printing",
    };
  }
  return null;
}

/** Which artwork of a card this printing uses, as a human ordinal.
 *
 * `p2` is Bandai's second additional artwork, so it is the *third* image of
 * the card - hence the +1. Only ever a last-resort disambiguator: two tiles
 * that would otherwise read identically. It is never shown on its own, and
 * `p1`/`r1` are never rendered raw. */
export function artOrdinalLabel(officialAssetVariant: string | null | undefined): string | null {
  if (!officialAssetVariant) return null;
  const match = /^p(\d+)$/.exec(officialAssetVariant.trim().toLowerCase());
  if (!match) return null;
  const index = Number(match[1]);
  if (!Number.isFinite(index) || index < 1) return null;
  return `Art ${index + 1}`;
}

/** Bandai's ORDINARY rarity tokens - how scarce the card is, and nothing else.
 *
 * SP Card and Treasure Rare are deliberately absent: they are special printing
 * categories, not points on this ladder, and live in SPECIAL_PRINT_TERMS
 * below. */
const RARITY_TERMS: Record<string, Term> = {
  C: { key: "rarity.c", label: "Common", definition: "The most widely printed rarity.", sourceLabel: "C", category: "rarity" },
  UC: { key: "rarity.uc", label: "Uncommon", definition: "Less frequent than Common.", sourceLabel: "UC", category: "rarity" },
  R: { key: "rarity.r", label: "Rare", definition: "Rarer than Uncommon.", sourceLabel: "R", category: "rarity" },
  SR: { key: "rarity.sr", label: "Super Rare", definition: "A step above Rare.", sourceLabel: "SR", category: "rarity" },
  SEC: { key: "rarity.sec", label: "Secret Rare", definition: "The scarcest pull in a set.", sourceLabel: "SEC", category: "rarity" },
  L: {
    key: "rarity.l",
    label: "Leader",
    definition: "The card you start the game with. A role, not a scarcity tier.",
    sourceLabel: "L",
    category: "rarity",
  },
  P: {
    key: "rarity.p",
    label: "Promo",
    definition: "Given away at events or with products, not pulled from packs.",
    sourceLabel: "P",
    category: "rarity",
  },
};

/** The single collector-facing filter value for SP Card.
 *
 * Bandai's own English catalogue token, and the value `GET /prints?rarity=`
 * expands to both raw source tokens server-side - see
 * services/api/app/services/rarity_facets.py, which owns the same constant.
 * The two must stay in step: this string is what the catalogue's facets offer
 * and what a filtered URL carries. */
export const SP_CARD_FILTER_VALUE = "SP CARD";

const SP_CARD_DEFINITION =
  "A special-art printing category, not a scarcity tier - it sits alongside " +
  "the card's rarity rather than replacing it, so an SP Card can also be a " +
  "Super Rare.";

/** The legend's version, which has no single print to point at and so has to
 * name both published tokens itself. A per-token entry below says which one
 * THAT printing carries via `sourceLabel`, and would only repeat itself if it
 * carried this sentence too. */
const SP_CARD_LEGEND_DEFINITION =
  `${SP_CARD_DEFINITION} Published in the Japanese catalogue as SPカード or SP P.`;

const TREASURE_RARE_DEFINITION =
  "Treasure Rare. A language-specific special-art printing. Artwork may " +
  "differ between English, Japanese, Chinese and other editions.";

/** Special print categories, keyed by every raw token that names one.
 *
 * Both Japanese `SPカード` and `SP P` map to the single collector-facing
 * "SP Card", as does the `SP CARD` alias the catalogue filters on: Bandai's
 * English catalogue publishes all of them as SP CARD, so surfacing them as
 * separate categories would invent a distinction Bandai itself does not make.
 * Each raw entry keeps its own `sourceLabel` so detail/help copy can still say
 * which token was published.
 *
 * TR is deliberately NOT merged into SP Card - it is a separate token in both
 * the Japanese and English catalogues, and it is language-specific, which SP
 * Card is not. */
const SPECIAL_PRINT_TERMS: Record<string, Term> = {
  [SP_CARD_FILTER_VALUE]: {
    key: "special_print.sp_card",
    label: "SP Card",
    definition: SP_CARD_LEGEND_DEFINITION,
    category: "special_print",
  },
  "SPカード": {
    key: "special_print.sp_card",
    label: "SP Card",
    definition: SP_CARD_DEFINITION,
    sourceLabel: "SPカード",
    category: "special_print",
  },
  "SP P": {
    key: "special_print.sp_card",
    label: "SP Card",
    definition: SP_CARD_DEFINITION,
    sourceLabel: "SP P",
    category: "special_print",
  },
  TR: {
    key: "special_print.treasure_rare",
    label: "Treasure Rare",
    shortLabel: "TR",
    definition: TREASURE_RARE_DEFINITION,
    sourceLabel: "TR",
    category: "special_print",
  },
};

/** The ordinary-rarity term for a raw token, or null when the token is not an
 * ordinary rarity at all.
 *
 * Null covers two different cases on purpose, and both mean "do not print a
 * rarity for this": a token this build has never seen, and a token that names
 * a special print rather than a scarcity tier. Callers that want the whole
 * picture use `classifyRarityToken`. */
export function rarityTerm(raw: string | null | undefined): Term | null {
  if (!raw) return null;
  return RARITY_TERMS[raw.trim()] ?? null;
}

/** The special-print term for a raw token, or null when it names none. */
export function specialPrintTerm(raw: string | null | undefined): Term | null {
  if (!raw) return null;
  return SPECIAL_PRINT_TERMS[raw.trim()] ?? null;
}

/** What one published rarity token actually says, split into the dimensions a
 * collector reads separately.
 *
 * At most one of the three is ever non-null. `unknownToken` is the fail-safe
 * passthrough: an unrecognised token is genuine published source metadata, and
 * a collector shown the raw value is better served than one shown an invented
 * meaning - so callers render it verbatim rather than dropping it. */
export interface RarityFacts {
  /** How scarce the card is, when the token says so. */
  rarity: Term | null;
  /** The special printing category, when the token names one. */
  specialPrint: Term | null;
  /** The raw token, when this build recognises it as neither. */
  unknownToken: string | null;
}

export function classifyRarityToken(raw: string | null | undefined): RarityFacts {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return { rarity: null, specialPrint: null, unknownToken: null };
  const rarity = rarityTerm(trimmed);
  if (rarity) return { rarity, specialPrint: null, unknownToken: null };
  const specialPrint = specialPrintTerm(trimmed);
  if (specialPrint) return { rarity: null, specialPrint, unknownToken: null };
  return { rarity: null, specialPrint: null, unknownToken: trimmed };
}

/** Terms that are not derived from a raw value - the vocabulary the catalogue
 * itself uses. Keyed so the legend and a tooltip read from one source. */
const STATIC_TERMS: Record<string, Term> = {
  "identity.found_in": {
    key: "identity.found_in",
    label: "Found in",
    definition:
      "The product this specific printing appeared in. It does not necessarily mean the card originated in that set.",
    category: "identity",
  },
  "identity.set": {
    key: "identity.set",
    label: "Set",
    definition: "The set the card was originally published in.",
    category: "identity",
  },
  "pricing.market_index": {
    key: "pricing.market_index",
    label: "Market Index",
    definition: "Atlas's reference price calculated from eligible pricing sources.",
    category: "pricing",
  },
  "pricing.source_range": {
    key: "pricing.source_range",
    label: "Source range",
    definition: "The lowest and highest eligible source prices currently used for comparison.",
    category: "pricing",
  },
};

/** Any term by key - static, printing, rarity or special print. Null when
 * unknown. */
export function getTerm(key: string): Term | null {
  if (STATIC_TERMS[key]) return STATIC_TERMS[key];
  const known = [
    printingTypeTerm("p1"),
    printingTypeTerm("r1"),
    ...Object.values(RARITY_TERMS),
    ...Object.values(SPECIAL_PRINT_TERMS),
  ].filter((t): t is Term => t !== null);
  return known.find((t) => t.key === key) ?? null;
}

/** The sentence the legend opens with.
 *
 * The whole point of the panel: the three vocabularies are not competing
 * answers to one question, so a print reading Super Rare AND SP Card AND Alt
 * Art is not a contradiction. Lives here rather than in the component so the
 * copy sits beside the terms it describes. */
export const LEGEND_INTRO =
  "Rarity, special print and printing describe three different things, so one " +
  "card can be all three at once - a Super Rare that is also an SP Card and an " +
  "Alt Art.";

export interface LegendSection {
  /** Stable id, used as a React key. */
  id: string;
  title: string;
  /** The section's own sentence, where the group needs explaining as a group
   * rather than term by term. */
  blurb?: string;
  terms: Term[];
}

/** The catalogue legend, grouped by dimension.
 *
 * The grouping is the substance, not decoration: seeing "SP Card" under
 * "Special print" rather than under "Rarity" is what stops it reading as a
 * scarcity tier. The ordinary rarities get a blurb instead of seven rows -
 * each is already explained on its own badge, and a seven-row ladder would
 * push the three headings off a phone screen, which is where the panel is
 * read.
 */
export const LEGEND_SECTIONS: LegendSection[] = [
  {
    id: "rarity",
    title: "Rarity",
    blurb:
      "How scarce the card is, as Bandai publishes it: Common, Uncommon, Rare, " +
      "Super Rare, Secret Rare. Leader and Promo are roles rather than scarcity tiers.",
    terms: [],
  },
  {
    id: "special_print",
    title: "Special print",
    blurb: "A special printing category. It sits alongside the card's rarity, not instead of it.",
    terms: [SPECIAL_PRINT_TERMS[SP_CARD_FILTER_VALUE], SPECIAL_PRINT_TERMS.TR],
  },
  {
    id: "printing",
    title: "Printing",
    blurb: "Which printing of the card this particular item is.",
    terms: [printingTypeTerm("p1")!, printingTypeTerm("r1")!],
  },
  {
    id: "identity",
    title: "Where it comes from",
    terms: [STATIC_TERMS["identity.set"], STATIC_TERMS["identity.found_in"]],
  },
  {
    id: "pricing",
    title: "Pricing",
    terms: [STATIC_TERMS["pricing.market_index"], STATIC_TERMS["pricing.source_range"]],
  },
];

/** Every legend term, flattened - for tests and for anything that needs the
 * vocabulary without the grouping. */
export const LEGEND_TERMS: Term[] = LEGEND_SECTIONS.flatMap((section) => section.terms);

/** Every ordinary rarity token this build can label, for tests and tooling. */
export const KNOWN_RARITY_TOKENS = Object.keys(RARITY_TERMS);

/** Every token that names a special print - raw source tokens and the
 * catalogue filter alias alike. */
export const KNOWN_SPECIAL_PRINT_TOKENS = Object.keys(SPECIAL_PRINT_TERMS);
