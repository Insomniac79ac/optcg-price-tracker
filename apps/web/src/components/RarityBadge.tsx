import { classifyRarityToken, type Term } from "@/lib/terminology";

/** Tones for the ordinary rarity ladder, keyed on the RAW token rather than
 * the collector-facing label so the map stays aligned with the API's own
 * vocabulary and a relabelling never silently drops a colour. */
const RARITY_STYLES: Record<string, string> = {
  L: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  SEC: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  SR: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  R: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  UC: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  C: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  P: "bg-teal-500/15 text-teal-300 ring-teal-500/30",
};

/** Tones for the special print categories, keyed on the term key.
 *
 * Deliberately outside the rarity ladder's palette: these are not points on
 * it, and a collector should be able to see at a glance that the fuchsia chip
 * is answering a different question from the violet one beside it. Treasure
 * Rare keeps its own tone rather than sharing SP Card's - it is a separate
 * published category, and a language-specific one. */
const SPECIAL_PRINT_STYLES: Record<string, string> = {
  "special_print.sp_card": "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
  "special_print.treasure_rare": "bg-orange-500/15 text-orange-300 ring-orange-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

const CHIP_CLASS =
  "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset";

/** One ordinary-rarity chip - how scarce the card is, and nothing else.
 *
 * Takes a resolved `Term`, so a special-print token cannot arrive here and be
 * dressed up as a rarity: the caller has to have classified it first. `title`
 * carries the definition as a baseline affordance; the catalogue legend is
 * the accessible, non-hover route to the same words.
 */
export function RarityTermBadge({ term }: { term: Term }) {
  const style = RARITY_STYLES[term.sourceLabel ?? ""] ?? DEFAULT_STYLE;
  return (
    <span className={`${CHIP_CLASS} ${style}`} title={`${term.label} — ${term.definition}`}>
      {term.label}
    </span>
  );
}

/** One special-print chip - SP Card, Treasure Rare.
 *
 * Renders `shortLabel` where the term has one, because "Treasure Rare" is
 * three times the width of the rarity chip beside it on a 390px tile and TR
 * is Bandai's own published short form. The full label is always in the
 * `title` and always in the legend, so the short form never carries the
 * meaning on its own.
 */
export function SpecialPrintBadge({ term }: { term: Term }) {
  const style = SPECIAL_PRINT_STYLES[term.key] ?? DEFAULT_STYLE;
  return (
    <span className={`${CHIP_CLASS} ${style}`} title={`${term.label} — ${term.definition}`}>
      {term.shortLabel ?? term.label}
    </span>
  );
}

/** A rarity token this build does not recognise, shown verbatim.
 *
 * The fail-safe path, and a component of its own for a reason: an unfamiliar
 * token is real published evidence a collector should see, but it carries no
 * definition and no tone, so it must not borrow the styling of a rarity we do
 * understand. Neutral, unexplained, and never dropped.
 */
export function UnknownRarityBadge({ token }: { token: string }) {
  return <span className={`${CHIP_CLASS} ${DEFAULT_STYLE}`}>{token}</span>;
}

/** One chip for a raw published rarity token, whatever it turns out to name.
 *
 * The entry point for every surface that holds a single rarity string and has
 * nowhere to put a second dimension - the collection, wishlist, market and
 * admin tables, and the catalogue's image placeholder. It classifies the
 * token and delegates, so `SPカード` renders as an SP Card chip rather than as
 * raw Japanese standing in for a scarcity tier, and an unrecognised token
 * still reaches the reader.
 *
 * Surfaces that CAN show the dimensions apart - the print catalogue tile and
 * the print detail page - do not use this: they read `rarityTerm` and
 * `specialPrint` off the print model and render the two chips themselves, so
 * a Super Rare SP Card shows both facts rather than only the one that
 * happened to be published in the rarity column.
 */
export function RarityBadge({ rarity }: { rarity: string }) {
  const { rarity: term, specialPrint, unknownToken } = classifyRarityToken(rarity);
  if (term) return <RarityTermBadge term={term} />;
  if (specialPrint) return <SpecialPrintBadge term={specialPrint} />;
  if (unknownToken) return <UnknownRarityBadge token={unknownToken} />;
  return null;
}
