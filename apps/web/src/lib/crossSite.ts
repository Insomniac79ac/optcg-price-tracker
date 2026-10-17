import { NextResponse } from "next/server";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function originOf(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/** CSRF guard for state-changing routes (collector and admin).
 *
 * Auth.js cookies are SameSite=Lax, which already keeps them off cross-site
 * POSTs in current browsers; this is the explicit second layer. A mutating
 * request must come from this site: `Sec-Fetch-Site`, when the browser sends
 * it, must be `same-origin`, and `Origin` must be present and equal to the
 * requested origin (or AUTH_URL's, the stable alias). Returns a ready 403
 * response to send, or null to continue. */
export function crossSiteRejection(request: Request): NextResponse | null {
  if (SAFE_METHODS.has(request.method.toUpperCase())) return null;
  const fetchSite = request.headers.get("sec-fetch-site");
  const origin = originOf(request.headers.get("origin"));
  const allowed = new Set([originOf(request.url), originOf(process.env.AUTH_URL)].filter(Boolean));
  const sameSite = (fetchSite === null || fetchSite === "same-origin") && origin !== null && allowed.has(origin);
  if (sameSite) return null;
  return NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
}
