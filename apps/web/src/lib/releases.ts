import { apiGet } from "./api";

export interface ReleaseCatalogueItem {
  release_product_id: number;
  official_code: string | null;
  display_name: string;
  source_catalogue: string;
  verification_status: string;
  print_count: number;
  created_at: string;
  released_on: string | null;
  chronology_available: boolean;
  release_date_source: "DATE_VERIFIED_CORROBORATED" | "DATE_VERIFIED_SINGLE_SOURCE" | null;
}

export interface ReleaseCatalogueList {
  items: ReleaseCatalogueItem[];
  chronology_available: boolean;
  ordering_basis: "released_on_desc_then_deterministic_fallback";
}

/** Server order is authoritative, including same-day ties and undated rows. */
export function fetchReleases(): Promise<ReleaseCatalogueList> {
  return apiGet<ReleaseCatalogueList>("/releases");
}

export function releaseLabel(release: ReleaseCatalogueItem): string {
  return [release.official_code, release.display_name].filter(Boolean).join(" — ");
}
