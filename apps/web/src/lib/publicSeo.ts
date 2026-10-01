import type { Metadata } from "next";
import type { PrintDetail } from "./prints";
import { publicSiteUrl } from "./publicRoutes";
import { artOrdinalLabel, classifyRarityToken, versionPrintingLabel } from "./terminology";
import { releaseLabelEnglish } from "./releaseNames";

export const absoluteUrl = (path: string) => new URL(path, publicSiteUrl()).toString();
export function pageMetadata(title: string, description: string, path: string, image = "/share/home/site", index = true): Metadata {
  const fullTitle = `${title} — Card Pirate`;
  return { title: { absolute: fullTitle }, description, alternates: { canonical: absoluteUrl(path) },
    robots: { index, follow: true },
    openGraph: { title: fullTitle, description, url: absoluteUrl(path), siteName: "Card Pirate", type: "website", images: [{ url: absoluteUrl(image), width: 1200, height: 630, alt: title }] },
    twitter: { card: "summary_large_image", title: fullTitle, description, images: [absoluteUrl(image)] } };
}
export function printIdentity(print: PrintDetail) {
  const name = print.name_en || print.name_jp || print.card_code;
  const release = print.release_product_id ? releaseLabelEnglish(print.release_code, print.release_name) : null;
  const printing = versionPrintingLabel(print.official_asset_variant);
  // The stable physical-print ID also distinguishes different artwork with the same label.
  return { name, detail: [release, printing, print.language?.toUpperCase()].filter(Boolean).join(" · ") };
}
// Titles describe the printing briefly; canonical IDs and full physical identity
// stay in the URL, description, visible page, social image and Product JSON-LD.
export function printPriceTitle(print: PrintDetail): string {
  const siblings = (print.siblings ?? []).filter((sibling) => sibling.card_print_id !== print.card_print_id);
  const label = versionPrintingLabel(print.official_asset_variant);
  const special = classifyRarityToken(print.rarity).specialPrint?.label;
  let variant: string | null = null;
  if (label === "Regular art" && siblings.length) variant = "Regular Art";
  if (label === "Alternate art") {
    const sharedLabel = siblings.some((sibling) => versionPrintingLabel(sibling.official_asset_variant) === label);
    variant = sharedLabel ? artOrdinalLabel(print.official_asset_variant) || "Alt Art" : "Alt Art";
  }
  if (label === "Reprint") variant = "Reprint";
  return [...new Set([printIdentity(print).name, print.card_code]), special, variant, "Price"].filter(Boolean).join(" ");
}
export const breadcrumbs = (items: { name: string; path: string }[]) => ({ "@context": "https://schema.org", "@type": "BreadcrumbList", itemListElement: items.map((item, i) => ({ "@type": "ListItem", position: i + 1, name: item.name, item: absoluteUrl(item.path) })) });
export function printProduct(print: PrintDetail) {
  const identity = printIdentity(print);
  return { "@context": "https://schema.org", "@type": "Product", "@id": absoluteUrl(`/prints/${print.card_print_id}#product`), url: absoluteUrl(`/prints/${print.card_print_id}`), name: `${identity.name} ${print.card_code} · ${identity.detail}`, sku: `card-print-${print.card_print_id}`, category: "One Piece trading card version", description: "Exact physical version with Japanese market price references. Card Pirate is not the seller.", image: print.display_image?.url || print.image_url || undefined, additionalProperty: [{ "@type": "PropertyValue", name: "Card code", value: print.card_code }, { "@type": "PropertyValue", name: "Canonical card ID", value: String(print.canonical_card_id) }, ...(print.release_product_id ? [{ "@type": "PropertyValue", name: "Release ID", value: String(print.release_product_id) }] : [])] };
}
export function serializeJsonLd(value: unknown) { return JSON.stringify(value).replace(/</g, "\\u003c"); }
export type PublicSearchParams = Record<string, string | string[] | undefined>;
export function searchParamsUrl(params: PublicSearchParams) {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) result.append(key, item);
  return result;
}
