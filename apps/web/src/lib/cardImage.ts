/** Which third-party image hosts this app will re-serve through its own
 * origin, and the helper that rewrites a card image URL to do so.
 *
 * Some card-artwork hosts send `Cross-Origin-Resource-Policy: same-site`,
 * which instructs browsers to refuse the image when it's embedded from
 * another site. Bandai's official card list
 * (`www.onepiece-cardgame.com`) - the host every `card_print.image_url`
 * points at - does exactly that, so a direct <img src> renders nothing but
 * the fallback placeholder no matter what CSP allows.
 *
 * Routing those hosts through `/api/card-image` makes the request
 * same-origin, which is a deliberate product decision to re-serve another
 * host's content from our own server rather than hotlink it (see
 * CardImageFrame's docstring, which flagged server-side fetching as a bigger
 * claim on a third party's content than hotlinking). Approved by the
 * operator on 2026-08-12 for the public print catalogue.
 *
 * Hosts that embed cleanly cross-origin (card.yuyu-tei.jp sends
 * `access-control-allow-origin: *` and no CORP) are deliberately NOT listed
 * here: they keep hotlinking directly, so we make the smaller claim wherever
 * the smaller claim works.
 */

/** Hosts the proxy route will fetch from. Exact hostname matches only - this
 * list is the entire reason `/api/card-image` is not an open proxy, so keep
 * it exact and keep it short. */
export const PROXIED_IMAGE_HOSTS = ["www.onepiece-cardgame.com"] as const;

export const CARD_IMAGE_PROXY_PATH = "/api/card-image";

export function isProxiedImageHost(hostname: string): boolean {
  return (PROXIED_IMAGE_HOSTS as readonly string[]).includes(hostname);
}

/** Returns the URL an <img> should actually load: the original for hosts that
 * embed fine, a same-origin proxy path for hosts that refuse cross-site
 * embedding. Anything unparseable is returned untouched - a malformed URL is
 * the image element's problem to fail on, not something to route through our
 * server. */
export function resolveCardImageUrl(imageUrl: string | null): string | null {
  if (!imageUrl) return null;
  let parsed: URL;
  try {
    parsed = new URL(imageUrl);
  } catch {
    return imageUrl;
  }
  if (parsed.protocol !== "https:" || !isProxiedImageHost(parsed.hostname)) {
    return imageUrl;
  }
  return `${CARD_IMAGE_PROXY_PATH}?u=${encodeURIComponent(imageUrl)}`;
}
