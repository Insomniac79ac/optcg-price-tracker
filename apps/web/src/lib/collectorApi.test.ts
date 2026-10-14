// @vitest-environment node
import { jwtVerify, decodeJwt } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { authMock } = vi.hoisted(() => ({ authMock: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: authMock }));

import {
  API_TOKEN_TTL_SECONDS,
  collectorAuthHeaders,
  collectorIdentity,
  crossSiteRejection,
  mintApiToken,
} from "./collectorApi";

const SECRET = "unit-test-api-jwt-secret";
const COLLECTOR = { user: { id: "google-123", email: "collector@example.com", name: "Nami" }, sessionKind: "collector", expires: "" } as const;
const ADMIN = { user: { id: "staging-admin", email: "admin@example.com", role: "admin" }, sessionKind: "admin", expires: "" } as const;

beforeEach(() => {
  vi.stubEnv("API_JWT_SECRET", SECRET);
  vi.stubEnv("AUTH_URL", "https://optcg-price-tracker-staging.vercel.app");
});
afterEach(() => {
  vi.unstubAllEnvs();
  authMock.mockReset();
});

describe("collectorIdentity (collector sessions only)", () => {
  it("returns the Google subject, email and name of a collector session", () => {
    expect(collectorIdentity(COLLECTOR as never)).toEqual({ sub: "google-123", email: "collector@example.com", name: "Nami" });
  });

  it.each([
    ["no session", null],
    ["an admin session", ADMIN],
    ["an expired admin session", { ...ADMIN, adminSessionExpired: true, user: { id: "staging-admin", email: "admin@example.com" } }],
    ["a session without a kind", { user: { id: "google-123", email: "collector@example.com" } }],
    ["a collector session without an email", { user: { id: "google-123" }, sessionKind: "collector" }],
    ["a collector session without a subject", { user: { email: "collector@example.com" }, sessionKind: "collector" }],
  ])("refuses %s", (_label, session) => {
    expect(collectorIdentity(session as never)).toBeNull();
  });
});

describe("mintApiToken", () => {
  it("signs a 5-minute HS256 token for the collector with the shared API secret", async () => {
    const before = Math.floor(Date.now() / 1000);
    const token = await mintApiToken({ sub: "google-123", email: "collector@example.com", name: "Nami" });
    const { payload, protectedHeader } = await jwtVerify(token, new TextEncoder().encode(SECRET));
    expect(protectedHeader.alg).toBe("HS256");
    expect(payload).toMatchObject({ sub: "google-123", email: "collector@example.com", name: "Nami" });
    expect(API_TOKEN_TTL_SECONDS).toBe(300);
    expect(payload.exp! - payload.iat!).toBe(300);
    expect(payload.iat!).toBeGreaterThanOrEqual(before);
  });

  it("refuses to mint without API_JWT_SECRET", async () => {
    vi.stubEnv("API_JWT_SECRET", "");
    await expect(mintApiToken({ sub: "s", email: "e@example.com" })).rejects.toThrow(/API_JWT_SECRET/);
  });
});

describe("collectorAuthHeaders", () => {
  it("mints a bearer header for a collector session", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    const headers = await collectorAuthHeaders();
    expect(headers?.Authorization).toMatch(/^Bearer /);
    expect(decodeJwt(headers!.Authorization.slice(7)).sub).toBe("google-123");
  });

  it("returns null for an admin session, so no phantom user is ever created", async () => {
    authMock.mockResolvedValueOnce(ADMIN);
    expect(await collectorAuthHeaders()).toBeNull();
  });

  it("returns null when signed out", async () => {
    authMock.mockResolvedValueOnce(null);
    expect(await collectorAuthHeaders()).toBeNull();
  });
});

describe("crossSiteRejection (CSRF on mutating routes)", () => {
  const url = "https://optcg-price-tracker-staging.vercel.app/api/me/preferences";
  const request = (method: string, headers: Record<string, string>) => new Request(url, { method, headers });

  it.each(["GET", "HEAD", "OPTIONS"])("lets a safe %s through", (method) => {
    expect(crossSiteRejection(request(method, { origin: "https://evil.example" }))).toBeNull();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"])("accepts a same-origin %s", (method) => {
    expect(crossSiteRejection(request(method, { origin: "https://optcg-price-tracker-staging.vercel.app", "sec-fetch-site": "same-origin" }))).toBeNull();
  });

  it("accepts the AUTH_URL origin from an immutable deployment URL", () => {
    const fromDeployment = new Request("https://optcg-price-tracker-staging-abc.vercel.app/api/me", {
      method: "DELETE",
      headers: { origin: "https://optcg-price-tracker-staging.vercel.app" },
    });
    expect(crossSiteRejection(fromDeployment)).toBeNull();
  });

  it.each([
    ["another origin", { origin: "https://evil.example" }],
    ["no Origin header", {}],
    ["a cross-site fetch", { origin: "https://optcg-price-tracker-staging.vercel.app", "sec-fetch-site": "cross-site" }],
    ["a same-site (sibling subdomain) fetch", { origin: "https://optcg-price-tracker-staging.vercel.app", "sec-fetch-site": "same-site" }],
    ["a null origin", { origin: "null" }],
  ])("refuses a mutating request with %s", async (_label, headers) => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      const rejected = crossSiteRejection(request(method, headers as Record<string, string>));
      expect(rejected?.status).toBe(403);
    }
  });
});
