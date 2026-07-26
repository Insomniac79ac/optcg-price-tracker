import { describe, expect, it } from "vitest";

import { sanitizeCallbackUrl } from "./callbackUrl";

describe("sanitizeCallbackUrl", () => {
  it("returns a safe relative path unchanged", () => {
    expect(sanitizeCallbackUrl("/collection/vault")).toBe("/collection/vault");
  });

  it("preserves the query string", () => {
    expect(sanitizeCallbackUrl("/wishlist?status=graded")).toBe("/wishlist?status=graded");
  });

  it("defaults to / when missing", () => {
    expect(sanitizeCallbackUrl(undefined)).toBe("/");
    expect(sanitizeCallbackUrl(null)).toBe("/");
    expect(sanitizeCallbackUrl("")).toBe("/");
  });

  it("rejects absolute URLs (open-redirect vector)", () => {
    expect(sanitizeCallbackUrl("https://evil.example.com/phish")).toBe("/");
  });

  it("rejects non-http(s) schemes", () => {
    expect(sanitizeCallbackUrl("javascript:alert(1)")).toBe("/");
  });

  it("rejects protocol-relative URLs", () => {
    expect(sanitizeCallbackUrl("//evil.example.com")).toBe("/");
  });

  it("rejects backslash-based protocol-relative tricks", () => {
    expect(sanitizeCallbackUrl("/\\evil.example.com")).toBe("/");
  });

  it("rejects embedded whitespace/control characters", () => {
    expect(sanitizeCallbackUrl("/foo\nbar")).toBe("/");
    expect(sanitizeCallbackUrl("/foo bar")).toBe("/");
  });

  it("rejects paths that don't start with a single slash", () => {
    expect(sanitizeCallbackUrl("collection")).toBe("/");
  });
});
