/** Security headers as next.config.ts emits them (security audit 2026-10-16,
 * F14). nextConfigImgSrc.test.ts covers img-src; this covers the rest. */
import { describe, expect, it } from "vitest";
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

  it("reports, without enforcing, the tighter policy proposed by the audit", async () => {
    const all = await headers();
    const reportOnly = all.get("Content-Security-Policy-Report-Only")!.split("; ");
    expect(reportOnly).toContain("object-src 'none'");
    expect(reportOnly).toContain("base-uri 'self'");
    expect(reportOnly).toContain("form-action 'self' https://accounts.google.com");
    expect(reportOnly).toContain("frame-src 'none'");
    // The enforced policy is unchanged until staging shows no reports.
    const enforced = all.get("Content-Security-Policy")!.split("; ");
    expect(enforced.find((d) => d.startsWith("object-src"))).toBeUndefined();
    expect(enforced.find((d) => d.startsWith("form-action"))).toBeUndefined();
  });

  it("reports with the same sources the site already loads from", async () => {
    const all = await headers();
    const pick = (header: string, name: string) =>
      all.get(header)!.split("; ").find((d) => d.startsWith(`${name} `));
    for (const name of ["script-src", "style-src", "img-src", "connect-src"]) {
      expect(pick("Content-Security-Policy-Report-Only", name)).toBe(pick("Content-Security-Policy", name));
    }
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
