/** The CSP `img-src` directive as next.config.ts actually emits it.
 *
 * cspImageOrigin.test.ts covers the helper in isolation; this covers the
 * wiring - that the configured origin really reaches the header, and that the
 * hotlinked hosts the catalogue already depends on are still there. The
 * config module reads process.env at import time, so each case resets the
 * module registry and re-imports it. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SETTING = "R2_PUBLIC_BASE_URL";

let original: string | undefined;

beforeEach(() => {
  original = process.env[SETTING];
});

afterEach(() => {
  if (original === undefined) delete process.env[SETTING];
  else process.env[SETTING] = original;
  vi.resetModules();
});

async function imgSrcDirective(configured: string | undefined): Promise<string> {
  vi.resetModules();
  if (configured === undefined) delete process.env[SETTING];
  else process.env[SETTING] = configured;

  const { default: config } = await import("../../next.config");
  const routes = await config.headers!();
  const csp = routes[0].headers.find((header) => header.key === "Content-Security-Policy");
  const directive = csp!.value.split("; ").find((part) => part.startsWith("img-src "));
  return directive!;
}

describe("next.config.ts img-src", () => {
  it("is unchanged when no owned-asset base URL is configured", async () => {
    await expect(imgSrcDirective(undefined)).resolves.toBe(
      "img-src 'self' data: https://card.yuyu-tei.jp https://cdn.snkrdunk.com",
    );
  });

  it("is unchanged when the setting is blank", async () => {
    await expect(imgSrcDirective("")).resolves.toBe(
      "img-src 'self' data: https://card.yuyu-tei.jp https://cdn.snkrdunk.com",
    );
    await expect(imgSrcDirective("   ")).resolves.toBe(
      "img-src 'self' data: https://card.yuyu-tei.jp https://cdn.snkrdunk.com",
    );
  });

  it("adds exactly the configured origin, keeping the existing hosts", async () => {
    await expect(imgSrcDirective("https://assets.example.com/display-images/")).resolves.toBe(
      "img-src 'self' data: https://card.yuyu-tei.jp https://cdn.snkrdunk.com " +
        "https://assets.example.com",
    );
  });

  it("carries no object key or path into the policy", async () => {
    const directive = await imgSrcDirective(
      "https://pub-abc123.r2.dev/display-images/sha256/00/",
    );
    expect(directive).toContain("https://pub-abc123.r2.dev");
    expect(directive).not.toContain("display-images");
    expect(directive).not.toContain("sha256");
  });

  it("introduces no wildcard host", async () => {
    const directive = await imgSrcDirective("https://pub-abc123.r2.dev/display-images/");
    expect(directive).not.toContain("*");
    expect(directive).not.toContain("*.r2.dev");
  });

  it("fails the build for an invalid configured value rather than omitting it", async () => {
    await expect(imgSrcDirective("http://assets.example.com/")).rejects.toThrow(/must use https/);
    await expect(imgSrcDirective("not a url")).rejects.toThrow(/not a valid absolute URL/);
    await expect(imgSrcDirective("https://user:pw@assets.example.com/")).rejects.toThrow(
      /must not contain credentials/,
    );
  });
});
