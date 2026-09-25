import { fetchPrintCatalogue, toPrintUiModel, type PrintCatalogueItem, type PrintUiModel } from "./prints";
import { classifyRarityToken } from "./terminology";
import { selectHeroFanPrints, utcDayKey } from "./heroFan";

export const RECENT_COHORT_SIZE = 16;
const HERO_COHORT_SIZE = 16;
export const fetchRecentFinds = () => fetchPrintCatalogue({ sort: "created_desc", limit: RECENT_COHORT_SIZE });

/** Rarity and treatment are different OR branches. Each request is bounded;
 * sending both families in one query would mistakenly intersect them. */
export async function fetchHeroCatalogue(): Promise<PrintUiModel[]> {
  const sr = await fetchPrintCatalogue({ rarity: ["SR"], sort: "created_desc", limit: HERO_COHORT_SIZE });
  const sp = sr.facets.rarities.filter((value) => classifyRarityToken(value).specialPrint?.key === "special_print.sp_card");
  const treatments = sr.facets.treatments.filter((value) => value === "parallel" || value === "sp");
  const branches = await Promise.allSettled([
    ...(sp.length ? [fetchPrintCatalogue({ rarity: sp, sort: "created_desc", limit: HERO_COHORT_SIZE })] : []),
    ...(treatments.length ? [fetchPrintCatalogue({ treatment: treatments, sort: "created_desc", limit: HERO_COHORT_SIZE })] : []),
  ]);
  const items: PrintCatalogueItem[] = [...sr.items];
  branches.forEach((branch) => { if (branch.status === "fulfilled") items.push(...branch.value.items); });
  return [...new Map(items.map((item) => [item.card_print_id, toPrintUiModel(item)])).values()];
}

export function isHomeHeroCategory(print: PrintUiModel): boolean {
  return classifyRarityToken(print.rarity).rarity?.key === "rarity.sr"
    || print.specialPrint?.key === "special_print.sp_card"
    || print.treatment === "parallel" || print.treatment === "sp";
}
export function homeHeroPrints(prints: PrintUiModel[], bucket: string): PrintUiModel[] {
  return selectHeroFanPrints(prints.filter(isHomeHeroCategory), bucket);
}
/** A daily ring through the recent cohort preserves ingestion order within
 * each selection, ignores prices, and guarantees a different next bucket
 * whenever the cohort contains more items than the visible four. */
export function rotateRecentFinds(prints: PrintUiModel[], bucket: string, size = 4): PrintUiModel[] {
  const unique = [...new Map(prints.map((print) => [print.cardPrintId, print])).values()];
  if (unique.length <= size) return unique;
  const day = Math.floor(Date.parse(`${bucket}T00:00:00Z`) / 86_400_000);
  const start = ((day % unique.length) + unique.length) % unique.length;
  return Array.from({ length: size }, (_, i) => unique[(start + i) % unique.length]);
}
export { utcDayKey };
