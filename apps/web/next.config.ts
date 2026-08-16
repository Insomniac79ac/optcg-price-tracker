import type { NextConfig } from "next";

import { buildImageSrcHosts } from "./src/lib/cspImageOrigin";

const isProd = process.env.NODE_ENV === "production";

// Browser-side code calls the API directly for per-user routes (see
// src/lib/api.ts's apiGet/apiPost - /collection, /grading, /collector use a
// bearer token from the NextAuth session rather than going through a
// server-side proxy route), so connect-src must allow whatever
// NEXT_PUBLIC_API_URL actually points at in this build, not just the dev
// defaults - otherwise those requests would be silently blocked by CSP in
// any deployment that isn't localhost.
function apiOrigin(): string | null {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

function buildConnectSrc(): string {
  const sources = new Set<string>(["'self'"]);
  const origin = apiOrigin();
  if (origin) sources.add(origin);
  // Dev-only fallback so a fresh checkout without NEXT_PUBLIC_API_URL set
  // still works against the default local API port - see
  // "Quick deploy flow" in docs/deployment.md for the production equivalent.
  if (!isProd) {
    sources.add("http://localhost:8000");
    sources.add("http://127.0.0.1:8000");
  }
  return Array.from(sources).join(" ");
}

// Next.js's dev server (fast refresh/HMR) needs 'unsafe-eval'; production
// builds don't. Both need 'unsafe-inline' for script-src - Next.js injects
// its hydration bootstrap as inline <script> tags in both modes, and this
// app doesn't wire up nonce-based CSP (see docs/deployment.md for the
// tradeoff) - so dropping 'unsafe-inline' here would break every page.
const scriptSrc = isProd ? "'self' 'unsafe-inline'" : "'self' 'unsafe-inline' 'unsafe-eval'";

// Card artwork is hotlinked directly from approved price-source CDNs (see
// components/ui/CardImageFrame.tsx's docstring and docs/market_index.md
// "Image hosting") - only the specific hosts we've actually verified serve
// real image content are allowlisted here, not a blanket `https:` (collector-
// first redesign audit, Phase 9 - "no unrestricted arbitrary image host
// configuration"). Add a new host here only after verifying it the same way
// (see docs/market_index.md).
//
// Bandai's card list (www.onepiece-cardgame.com), the host every
// card_print.image_url points at, is deliberately NOT here: it serves
// `Cross-Origin-Resource-Policy: same-site`, so a browser refuses to embed it
// cross-origin whatever CSP says. Those images are re-served same-origin
// through /api/card-image instead (already covered by 'self'), so this list
// stays limited to hosts we genuinely hotlink - see src/lib/cardImage.ts.
//
// cdn.snkrdunk.com serves the verified display images selected by
// app.services.display_image. Checked 2026-08-13: it sends no
// Cross-Origin-Resource-Policy and no CORS headers, so a plain <img> embeds it
// cross-origin fine and it needs no proxy entry - the smaller claim, same call
// as card.yuyu-tei.jp above.
const APPROVED_IMAGE_HOSTS = ["https://card.yuyu-tei.jp", "https://cdn.snkrdunk.com"];

// Images we mirror into our own object storage are served from the origin
// named by R2_PUBLIC_BASE_URL - the same setting the API builds
// `display_image.url` from - so CSP has to permit that exact origin or the
// browser blocks the request before it is sent (which is precisely what
// happened to card_print_id=1 on staging: see
// docs/display_image_print1_frontend_qa_2026-08-16.pdf). Configuration, not a
// hardcoded host: staging's bucket is on *.r2.dev today and production will
// use a custom asset domain. Unset is a supported state and leaves the list
// above exactly as it was; an invalid value throws here and fails the build.
// See src/lib/cspImageOrigin.ts.
const IMAGE_HOSTS = buildImageSrcHosts(APPROVED_IMAGE_HOSTS, process.env.R2_PUBLIC_BASE_URL);

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src ${scriptSrc}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: ${IMAGE_HOSTS.join(" ")}`,
  `connect-src ${buildConnectSrc()}`,
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
        ],
      },
    ];
  },
};

export default nextConfig;
