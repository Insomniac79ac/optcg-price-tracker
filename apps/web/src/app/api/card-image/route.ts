import { NextResponse } from "next/server";

import { isProxiedImageHost } from "@/lib/cardImage";

/** Re-serves card artwork from the small set of approved third-party hosts
 * that refuse cross-site embedding (see src/lib/cardImage.ts for which, and
 * why this exists at all).
 *
 * This route is an image proxy, so the thing that matters most about it is
 * that it can never become a *general* proxy:
 *
 *  - the target host must be on PROXIED_IMAGE_HOSTS, matched on exact
 *    hostname after parsing - not a prefix/suffix/`includes` test, which is
 *    how allowlists like this usually get bypassed
 *    (`www.onepiece-cardgame.com.evil.tld`);
 *  - https only, so it can't be pointed at internal `http://` services;
 *  - redirects are not followed, so an approved host can't bounce the
 *    request onward to somewhere unapproved (or to a link-local metadata
 *    address);
 *  - the upstream response must actually be an image, and is capped, so this
 *    can't be used to shift arbitrary bulk content through our origin;
 *  - no cookies, credentials, or client headers are forwarded upstream, and
 *    no upstream headers except content-type reach the client.
 */

const MAX_BYTES = 8 * 1024 * 1024; // a 600x838 card PNG is ~250KB
const UPSTREAM_TIMEOUT_MS = 15_000;

function reject(status: number, reason: string): NextResponse {
  return NextResponse.json({ error: reason }, { status });
}

export async function GET(request: Request): Promise<NextResponse> {
  const target = new URL(request.url).searchParams.get("u");
  if (!target) return reject(400, "Missing image url");

  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return reject(400, "Malformed image url");
  }

  if (parsed.protocol !== "https:") return reject(400, "Only https image urls are proxied");
  if (!isProxiedImageHost(parsed.hostname)) return reject(403, "Image host is not approved");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  let upstream: Response;
  try {
    upstream = await fetch(parsed.toString(), {
      // No credentials and no forwarded client headers - this request is
      // ours, not a replay of the visitor's.
      redirect: "manual",
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "image/*" },
    });
  } catch {
    return reject(502, "Could not fetch image");
  } finally {
    clearTimeout(timeout);
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    return reject(502, "Image host redirected");
  }
  if (!upstream.ok) return reject(502, "Image host returned an error");

  const contentType = upstream.headers.get("content-type") ?? "";
  if (!contentType.startsWith("image/")) return reject(502, "Upstream response was not an image");

  const declaredLength = Number(upstream.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_BYTES) return reject(502, "Image too large");

  const body = await upstream.arrayBuffer();
  if (body.byteLength > MAX_BYTES) return reject(502, "Image too large");

  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(body.byteLength),
      // Card artwork is immutable per URL (Bandai versions its images with a
      // ?query suffix), so this is safe to cache hard at the edge.
      "Cache-Control": "public, max-age=86400, s-maxage=604800, immutable",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
