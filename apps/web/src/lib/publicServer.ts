import "server-only";
import { cache } from "react";
import type { PrintDetail, PrintCatalogueList } from "./prints";
import type { ReleaseCatalogueList } from "./releases";
import type { MarketValue } from "./marketValue";

// Public reads only: no cookie, session, token or private API is forwarded.
// Cache bounded public responses, never relabel retrieval time as source freshness.
export const publicRead = cache(async <T,>(path: string): Promise<T | null> => {
  try {
    const origin = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const response = await fetch(`${origin.replace(/\/$/, "")}${path}`, { next: { revalidate: 300 }, signal: AbortSignal.timeout(6000) });
    if (!response.ok) return null;
    return await response.json() as T;
  } catch { return null; }
});
export const readPrint = (printId: string) => /^\d+$/.test(printId) ? publicRead<PrintDetail>(`/prints/${printId}`) : Promise.resolve(null);
export const readReleases = () => publicRead<ReleaseCatalogueList>("/releases");
export const readCatalogue = (query: string) => publicRead<PrintCatalogueList>(`/prints?${query}`);
export const readMarket = (id: number | null) => publicRead<MarketValue>(`/analytics/market-value?window=7d${id ? `&release_product_id=${id}` : ""}`);
