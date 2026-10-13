import { track } from "@vercel/analytics";

/** Site analytics (Vercel Web Analytics, Collector v1 plan §F2, owner Q3).
 *
 * Privacy contract, enforced here rather than at each call site:
 * - Only the custom events named in §F2 can be sent; anything else is dropped.
 * - Event properties are an allowlist: `page_type` (a fixed vocabulary) and
 *   `release_code` (an official set code such as "OP-01"). Every other key,
 *   and any value that does not match, is dropped - so a user id, email,
 *   quantity or price paid can never be sent even if a caller passes one.
 * - Page views and events carry the path only: query strings and fragments
 *   are stripped, and admin/API paths are not sent at all.
 * - No session replay (Vercel Web Analytics has none; nothing else is added).
 *
 * Collection stays off until NEXT_PUBLIC_VERCEL_WEB_ANALYTICS is "1"
 * (build-time). Web Analytics must also be enabled on the Vercel project:
 * until it is, the collection script does not exist and loading it would
 * only fail. */

export const ANALYTICS_EVENTS = [
  "sign_in_started",
  "sign_in_completed",
  "collection_add",
  "collection_remove",
  "watch_add",
  "watch_remove",
  "account_export",
  "account_delete",
  "share_card",
] as const;
export type AnalyticsEventName = (typeof ANALYTICS_EVENTS)[number];

export const ANALYTICS_PAGE_TYPES = [
  "home",
  "cards",
  "card",
  "market",
  "collection",
  "watchlist",
  "account",
  "sign_in",
  "info",
] as const;
export type AnalyticsPageType = (typeof ANALYTICS_PAGE_TYPES)[number];

export type AnalyticsProperties = { page_type?: AnalyticsPageType; release_code?: string };

const RELEASE_CODE = /^[A-Z]{2,4}-\d{2,3}$/;

export function analyticsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS === "1";
}

/** Keeps only the allowlisted properties with valid values. */
export function sanitizeAnalyticsProperties(properties: unknown): AnalyticsProperties {
  const clean: AnalyticsProperties = {};
  if (!properties || typeof properties !== "object") return clean;
  const { page_type: pageType, release_code: releaseCode } = properties as Record<string, unknown>;
  if (typeof pageType === "string" && (ANALYTICS_PAGE_TYPES as readonly string[]).includes(pageType)) {
    clean.page_type = pageType as AnalyticsPageType;
  }
  if (typeof releaseCode === "string" && RELEASE_CODE.test(releaseCode)) {
    clean.release_code = releaseCode;
  }
  return clean;
}

/** Sends one allowlisted custom event. Unknown names are dropped. */
export function trackEvent(name: AnalyticsEventName, properties?: AnalyticsProperties): void {
  if (!analyticsEnabled()) return;
  if (!(ANALYTICS_EVENTS as readonly string[]).includes(name)) return;
  track(name, sanitizeAnalyticsProperties(properties));
}

const UNTRACKED_PREFIXES = ["/admin", "/api/"];

/** `beforeSend` for page views and events: path only, never admin/API. */
export function scrubAnalyticsEvent<T extends { url: string }>(event: T): T | null {
  let url: URL;
  try {
    url = new URL(event.url);
  } catch {
    return null;
  }
  const path = url.pathname;
  if (UNTRACKED_PREFIXES.some((prefix) => path === prefix.replace(/\/$/, "") || path.startsWith(prefix))) {
    return null;
  }
  return { ...event, url: `${url.origin}${path}` };
}
