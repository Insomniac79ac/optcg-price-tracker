import { describe, expect, it } from "vitest";

import {
  ImageOriginConfigError,
  buildImageSrcHosts,
  ownedAssetImageOrigin,
} from "./cspImageOrigin";

const APPROVED = ["https://card.yuyu-tei.jp", "https://cdn.snkrdunk.com"] as const;

describe("ownedAssetImageOrigin", () => {
  it("treats unset and blank as 'no owned asset origin configured'", () => {
    expect(ownedAssetImageOrigin(undefined)).toBeNull();
    expect(ownedAssetImageOrigin(null)).toBeNull();
    expect(ownedAssetImageOrigin("")).toBeNull();
    expect(ownedAssetImageOrigin("   ")).toBeNull();
  });

  it("derives the origin of a plain https base URL", () => {
    expect(ownedAssetImageOrigin("https://assets.example.com")).toBe("https://assets.example.com");
  });

  it("keeps only the origin when the base URL carries a path", () => {
    expect(ownedAssetImageOrigin("https://assets.example.com/cards/")).toBe(
      "https://assets.example.com",
    );
  });

  it("drops query and fragment as well as path", () => {
    expect(ownedAssetImageOrigin("https://assets.example.com/cards/deep/?v=2#frag")).toBe(
      "https://assets.example.com",
    );
  });

  it("is unaffected by a trailing slash", () => {
    const withSlash = ownedAssetImageOrigin("https://assets.example.com/");
    const withoutSlash = ownedAssetImageOrigin("https://assets.example.com");
    expect(withSlash).toBe(withoutSlash);
    expect(withSlash).toBe("https://assets.example.com");
  });

  it("keeps an explicit non-default port, which is part of the origin", () => {
    expect(ownedAssetImageOrigin("https://assets.example.com:8443/cards/")).toBe(
      "https://assets.example.com:8443",
    );
  });

  it("ignores surrounding whitespace in the configured value", () => {
    expect(ownedAssetImageOrigin("  https://assets.example.com/cards/  ")).toBe(
      "https://assets.example.com",
    );
  });

  it("never emits a wildcard, even for a subdomain of a shared provider", () => {
    const origin = ownedAssetImageOrigin("https://pub-abc123.r2.dev/display-images/");
    expect(origin).toBe("https://pub-abc123.r2.dev");
    expect(origin).not.toContain("*");
  });

  it("rejects http rather than silently omitting the origin", () => {
    expect(() => ownedAssetImageOrigin("http://assets.example.com/")).toThrow(
      ImageOriginConfigError,
    );
    expect(() => ownedAssetImageOrigin("http://assets.example.com/")).toThrow(/must use https/);
  });

  it("rejects a malformed value", () => {
    expect(() => ownedAssetImageOrigin("not a url")).toThrow(ImageOriginConfigError);
    expect(() => ownedAssetImageOrigin("assets.example.com/cards")).toThrow(
      /not a valid absolute URL/,
    );
  });

  it("rejects a URL carrying credentials", () => {
    expect(() => ownedAssetImageOrigin("https://user:secret@assets.example.com/")).toThrow(
      ImageOriginConfigError,
    );
    expect(() => ownedAssetImageOrigin("https://user@assets.example.com/")).toThrow(
      /must not contain credentials/,
    );
  });

  it("names the setting but never echoes the configured value in errors", () => {
    let message = "";
    try {
      ownedAssetImageOrigin("https://user:hunter2@assets.example.com/");
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).toContain("R2_PUBLIC_BASE_URL");
    expect(message).not.toContain("hunter2");
    expect(message).not.toContain("assets.example.com");
  });
});

describe("buildImageSrcHosts", () => {
  it("leaves the approved hosts exactly as-is when nothing is configured", () => {
    expect(buildImageSrcHosts(APPROVED, undefined)).toEqual([...APPROVED]);
    expect(buildImageSrcHosts(APPROVED, "")).toEqual([...APPROVED]);
    expect(buildImageSrcHosts(APPROVED, "   ")).toEqual([...APPROVED]);
  });

  it("appends the configured origin without disturbing the existing hosts", () => {
    expect(buildImageSrcHosts(APPROVED, "https://assets.example.com/cards/")).toEqual([
      "https://card.yuyu-tei.jp",
      "https://cdn.snkrdunk.com",
      "https://assets.example.com",
    ]);
  });

  it("does not duplicate an origin that is already approved", () => {
    const hosts = buildImageSrcHosts(APPROVED, "https://cdn.snkrdunk.com/mirror/");
    expect(hosts).toEqual([...APPROVED]);
    expect(hosts.filter((host) => host === "https://cdn.snkrdunk.com")).toHaveLength(1);
  });

  it("propagates a configuration error rather than dropping the origin", () => {
    expect(() => buildImageSrcHosts(APPROVED, "http://assets.example.com/")).toThrow(
      ImageOriginConfigError,
    );
  });
});
