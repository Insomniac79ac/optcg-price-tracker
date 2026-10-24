/** Security headers as next.config.ts emits them (security audit 2026-10-16,
 * F14). nextConfigImgSrc.test.ts covers img-src; this covers the rest. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { PHASE_PRODUCTION_SERVER } from "next/constants";

import loadConfig from "../../next.config";

async function headers(): Promise<Map<string, string>> {
  const routes = await loadConfig(PHASE_PRODUCTION_SERVER).headers!();
  expect(routes).toHaveLength(1);
  expect(routes[0].source).toBe("/(.*)");
  return new Map(routes[0].headers.map((h) => [h.key, h.value]));
}

describe("next.config.ts security headers", () => {
  it("sends HSTS for two years with subdomains and without preload", async () => {
    const hsts = (await headers()).get("Strict-Transport-Security");
    expect(hsts).toBe("max-age=63072000; includeSubDomains");
  });

  it("enforces the tighter policy proposed by the audit", async () => {
    const csp = (await headers()).get("Content-Security-Policy")!.split("; ");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self' https://accounts.google.com");
    expect(csp).toContain("frame-src 'none'");
    expect(csp).toContain("font-src 'self'");
    expect(csp).toContain("manifest-src 'self'");
    expect(csp).toContain("worker-src 'self'");
  });

  it("no longer sends the report-only copy", async () => {
    expect((await headers()).has("Content-Security-Policy-Report-Only")).toBe(false);
  });

  it("keeps the directives the site already relies on", async () => {
    const csp = (await headers()).get("Content-Security-Policy")!.split("; ");
    expect(csp[0]).toBe("default-src 'self'");
    expect(csp).toContain("style-src 'self' 'unsafe-inline'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp.find((d) => d.startsWith("script-src "))).toMatch(/^script-src 'self' 'unsafe-inline'/);
    expect(csp.find((d) => d.startsWith("connect-src "))).toMatch(/^connect-src 'self'/);
  });

  it("turns off powerful features the site never uses", async () => {
    expect((await headers()).get("Permissions-Policy")).toBe(
      "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
    );
  });
});

describe("next.config.ts search indexing header", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("sends X-Robots-Tag noindex on every response unless SITE_SEARCH_INDEXING=on", async () => {
    vi.stubEnv("SITE_SEARCH_INDEXING", "");
    expect((await headers()).get("X-Robots-Tag")).toBe("noindex, nofollow");
    vi.stubEnv("SITE_SEARCH_INDEXING", "on");
    expect((await headers()).has("X-Robots-Tag")).toBe(false);
  });
});
