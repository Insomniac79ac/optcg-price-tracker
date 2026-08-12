import type { NextConfig } from "next";

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
// www.onepiece-cardgame.com is Bandai's official card list, the host every
// card_print.image_url points at (all 20 prints served by GET /prints).
// Verified 2026-08-12 before being added here: each URL returns HTTP 200,
// Content-Type image/png, a real 600x838 card scan, with no Referer sent -
// which is what the browser will do, since both this app's Referrer-Policy
// header and CardImageFrame's referrerPolicy are no-referrer.
const APPROVED_IMAGE_HOSTS = [
  "https://card.yuyu-tei.jp",
  "https://www.onepiece-cardgame.com",
];

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src ${scriptSrc}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: ${APPROVED_IMAGE_HOSTS.join(" ")}`,
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
