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
  toPrintUiModel,
  type PrintCatalogueItem,
} from "./prints";

/** One palette row, from either search backend. */
export interface PaletteCardResult {
  key: string;
  title: string;
  subtitle: string;
  /** Always /prints/{card_print_id}.
   *
   * Never /cards/{card_id}: those are different namespaces whose numbers do
   * not correspond, and the legacy card route is not public anyway. */
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
  if (model.isDistinctTreatment) parts.push(model.treatment);

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
