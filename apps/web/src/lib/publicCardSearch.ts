// Card search for the public command palette.
//
// The palette's original card search went through /api/search, which requires
// a session - so a signed-out visitor typing "kaido" got a silent 401 and the
// palette showed "No matches" for a card that plainly exists. That endpoint
// stays authenticated; this module gives anonymous visitors the same public
// print catalogue that /cards already searches (GET /prints?q=), so the two
// surfaces can never disagree about what exists.
//
// Nothing here re-derives print identity, Market Index values or image
// selection: it maps whatever toPrintUiModel already produced into the few
// fields a palette row needs.

import {
  fetchPrintCatalogue,
  resolveCanonicalPrintIdentity,
  toPrintUiModel,
  type PrintCatalogueItem,
} from "./prints";

/** One palette row, from either search backend. */
export interface PaletteCardResult {
  key: string;
  title: string;
  subtitle: string;
  /** Where the row goes. A canonical family row points at
   * /cards/code/{card_code}; the older print row points at
   * /prints/{card_print_id}.
   *
   * Never /cards/{legacy_id}: that is a different namespace whose numbers do
   * not correspond to canonical ids, and its table disagrees with the
   * catalogue about which card a code names. */
  url: string;
}

/** Small enough to stay a single request and short enough to scan. */
export const PUBLIC_CARD_SEARCH_LIMIT = 8;

/** Below this, a query is too short to be worth a request. */
export const MIN_QUERY_LENGTH = 2;

/** One catalogue item as a palette row.
 *
 * The subtitle carries the card code, its set, and the treatment when the
 * treatment is one worth naming - which is what keeps a card's base and
 * parallel printings distinguishable in a list where both share a name. */
export function printToPaletteResult(item: PrintCatalogueItem): PaletteCardResult {
  const model = toPrintUiModel(item);
  const parts = [model.cardCode];
  if (model.releaseCode) parts.push(model.releaseCode);
  if (model.isDistinctTreatment && model.treatment) parts.push(model.treatment);

  return {
    key: `print-${model.cardPrintId}`,
    title: model.displayName,
    subtitle: parts.join(" · "),
    url: `/prints/${model.cardPrintId}`,
  };
}

/** Search the public print catalogue. Rejects rather than resolving empty, so
 * a caller can tell a failed search from a genuinely empty one. */
export async function searchPublicPrints(
  query: string,
  limit: number = PUBLIC_CARD_SEARCH_LIMIT,
): Promise<PaletteCardResult[]> {
  const list = await fetchPrintCatalogue({ q: query, limit });
  return list.items.map(printToPaletteResult);
}

// ---------------------------------------------------------------------------
// Canonical family search
// ---------------------------------------------------------------------------
//
// WHY FAMILIES, NOT PRINTS. A print row per result makes one card appear five
// times (OP04-044 Kaido has five printings), and picking one of them to stand
// for the card would be inventing a "representative printing" the catalogue
// does not have. A collector searching "Kaido" is looking for the CARD; which
// printing they own is the next question, and the printing chooser at
// /cards/code/{card_code} is the surface that asks it.
//
// WHY NOT THE LEGACY `cards` TABLE. The authenticated palette branch used to
// search it through /api/search. That table holds 25 rows against 2,710
// canonical cards, 10 of its rows name a different character than their own
// card_code resolves to, and 4 codes appear twice with conflicting names - so
// it produced duplicate results whose titles contradicted the page they led
// to. Both branches now read the same public canonical catalogue, so a
// signed-in and a signed-out collector are shown the same truth.

/** One canonical card, however many printings it has. */
export interface CanonicalFamilyResult {
  key: string;
  cardCode: string;
  /** The canonical name, or null when the family's own records disagree. */
  name: string | null;
  /** How many active printings this family has in the catalogue. */
  printingCount: number;
  /** Always /cards/code/{card_code} - never a single print, because a family
   * result must not choose a printing on the collector's behalf. */
  url: string;
}

/** `/prints?q=` pages at 100; a family spans up to 9 printings, so one page is
 * ample to fill a palette list. */
export const FAMILY_SEARCH_FETCH_LIMIT = 100;

export function familyRouteFor(cardCode: string): string {
  return `/cards/code/${encodeURIComponent(cardCode)}`;
}

/** Collapse catalogue items into one result per canonical card.
 *
 * Grouped by `canonical_card_id` - the catalogue's own identity - never by
 * name, so two cards that share a name stay separate and one card whose rows
 * disagree about its name still collapses to a single family.
 *
 * Order is the order the catalogue returned (card_code ascending by default),
 * kept stable so the same query always lists the same families in the same
 * places. `limit` truncates families, not prints, so a five-printing card
 * costs one row rather than five.
 *
 * A family whose records disagree on a name keeps `name: null` and is still
 * listed under its card code: the code is the part every record agrees on, and
 * hiding the card entirely would be a worse answer than naming it by code.
 */
export function groupPrintsIntoFamilies(
  items: PrintCatalogueItem[],
  limit: number = PUBLIC_CARD_SEARCH_LIMIT,
): CanonicalFamilyResult[] {
  const byCanonicalId = new Map<number, PrintCatalogueItem[]>();
  for (const item of items) {
    const bucket = byCanonicalId.get(item.canonical_card_id);
    if (bucket) bucket.push(item);
    else byCanonicalId.set(item.canonical_card_id, [item]);
  }

  const families: CanonicalFamilyResult[] = [];
  for (const [canonicalCardId, group] of byCanonicalId) {
    // Every row in a canonical group shares its card_code; taken from the
    // group rather than from the query, so a partial-code search still labels
    // each family with its own full code.
    const cardCode = group[0].card_code;
    families.push({
      key: `family-${canonicalCardId}`,
      cardCode,
      name: resolveCanonicalPrintIdentity(group)?.name ?? null,
      printingCount: group.length,
      url: familyRouteFor(cardCode),
    });
    if (families.length >= limit) break;
  }
  return families;
}

/** One canonical family as a palette row.
 *
 * No image: a family has no single artwork, and choosing one printing's art to
 * represent the card is exactly the invented "representative printing" this
 * design refuses. The printing count is what tells a collector there is a
 * choice waiting.
 */
export function familyToPaletteResult(family: CanonicalFamilyResult): PaletteCardResult {
  const parts = [family.cardCode];
  if (family.printingCount > 1) parts.push(`${family.printingCount} printings`);

  return {
    key: family.key,
    // Named by its code when the catalogue's own records disagree - never by a
    // guessed name, and never by the legacy card row's name.
    title: family.name ?? family.cardCode,
    subtitle: parts.join(" · "),
    url: family.url,
  };
}

/** Search the public catalogue and return one row per canonical card. */
export async function searchPublicCardFamilies(
  query: string,
  limit: number = PUBLIC_CARD_SEARCH_LIMIT,
): Promise<PaletteCardResult[]> {
  const list = await fetchPrintCatalogue({ q: query, limit: FAMILY_SEARCH_FETCH_LIMIT });
  return groupPrintsIntoFamilies(list.items, limit).map(familyToPaletteResult);
}
