import type { PrintCatalogueList } from "./prints";

export interface CatalogueSnapshot {
  query: string;
  data: PrintCatalogueList;
  nextOffset: number;
  scrollY: number;
  savedAt: number;
}
const STORAGE_KEY = "atlas-catalogue-v1";
const HISTORY_KEY = "atlasCatalogueSnapshot";

/** Each browser history entry points to its own snapshot. No API offset or
 * global scroll-restoration setting is changed. Storage failure is harmless. */
export function saveCatalogueSnapshot(snapshot: Omit<CatalogueSnapshot, "savedAt">) {
  try {
    const id = window.history.state?.[HISTORY_KEY] ?? crypto.randomUUID();
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, CatalogueSnapshot>;
    stored[id] = { ...snapshot, savedAt: Date.now() };
    const newest = Object.entries(stored).sort((a, b) => b[1].savedAt - a[1].savedAt).slice(0, 6);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(newest)));
    window.history.replaceState({ ...window.history.state, [HISTORY_KEY]: id }, "");
  } catch { /* Browsing and native Back still work with storage disabled. */ }
}

export function readCatalogueSnapshot(query: string): CatalogueSnapshot | null {
  try {
    const id = window.history.state?.[HISTORY_KEY];
    if (!id) return null;
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}");
    const entry = stored[id] as CatalogueSnapshot | undefined;
    return entry?.query === query && Date.now() - entry.savedAt < 30 * 60_000 ? entry : null;
  } catch { return null; }
}
