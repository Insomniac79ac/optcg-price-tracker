/**
 * Sign-in return path for one print page.
 *
 * The callback is the page's own path, `/prints/<id>`, taken only from the
 * route segment. A query string, Host, or forwarded header is not an input:
 * a callback copied from the request would be an open redirect. `untrusted`
 * is accepted so a test can hand those values in and prove they are unused.
 */

export type UntrustedPrintRequest = {
  searchParams?: URLSearchParams | Record<string, string | string[] | undefined>;
  headers?: Headers | Record<string, string | string[] | undefined>;
  url?: string;
};

/** Digits only, so the segment cannot smuggle a scheme, a host, or another path. */
const ROUTE_ID = /^[0-9]+$/;

export function printSignInCallbackPath(printId: string, untrusted?: UntrustedPrintRequest): string | null {
  void untrusted;
  if (!ROUTE_ID.test(printId)) return null;
  return `/prints/${printId}`;
}

/** Same-origin relative sign-in URL whose callback is this print's own path. */
export function printSignInHref(printId: string, untrusted?: UntrustedPrintRequest): string | null {
  const path = printSignInCallbackPath(printId, untrusted);
  if (!path) return null;
  return `/sign-in?callbackUrl=${encodeURIComponent(path)}`;
}

/**
 * Href for a signed-out first render, or null for a collector session.
 * The URL is chosen before the session is consulted, so the session can
 * only hide the link, never change where it points.
 */
export function signedOutPrintSignInHref(
  printId: string,
  session: { sessionKind?: string | null } | null,
  untrusted?: UntrustedPrintRequest,
): string | null {
  const href = printSignInHref(printId, untrusted);
  if (!href || session?.sessionKind === "collector") return null;
  return href;
}
