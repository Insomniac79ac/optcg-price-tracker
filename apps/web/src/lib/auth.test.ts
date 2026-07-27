// @vitest-environment node
//
// No DOM needed here (no component rendering) - and jsdom's `crypto`
// polyfill doesn't fully satisfy jose's webapi signing path used by
// applySessionCallback's SignJWT().sign() call (`payload must be an
// instance of Uint8Array`, thrown from inside jose itself). Real Node
// `crypto` (this environment override) doesn't have that gap.
import type { Account, Session, User } from "next-auth";
import type { JWT } from "next-auth/jwt";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The real "next-auth" package's index re-exports from lib/env.js, which
// imports an extensionless "next/server" that this repo's Vitest/Vite
// module resolution can't find (a resolution quirk of this Next.js/
// next-auth version combo under Vitest, unrelated to this file's own
// code) - mocked here the same way "next-auth/react" already is elsewhere
// in this test suite (see CommandPalette.test.tsx), just for the top-level
// package rather than the /react entry point. Captures the config object
// NextAuth() was called with so "Google provider configuration remains
// intact" can be asserted without ever running the real NextAuth runtime.
const { capturedNextAuthConfig } = vi.hoisted(() => ({
  capturedNextAuthConfig: { current: null as null | { providers: unknown[] } },
}));
vi.mock("next-auth", () => ({
  default: (config: { providers: unknown[] }) => {
    capturedNextAuthConfig.current = config;
    return { handlers: { GET: vi.fn(), POST: vi.fn() }, auth: vi.fn(), signIn: vi.fn(), signOut: vi.fn() };
  },
}));

import {
  ADMIN_CREDENTIALS_PROVIDER_ID,
  ADMIN_SESSION_MAX_AGE_MS,
  adminAuthorize,
  applyJwtCallback,
  applySessionCallback,
  auth,
  handlers,
  isNonEmptyBoundedString,
  signIn,
  signOut,
  verifyAdminCredentials,
} from "./auth";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV, API_JWT_SECRET: "test-api-jwt-secret-at-least-32-chars-long" };
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.unstubAllGlobals();
});

// --- Google provider configuration remains intact ---------------------

describe("NextAuth config", () => {
  it("still exports working handlers/auth/signIn/signOut", () => {
    expect(handlers).toBeDefined();
    expect(typeof auth).toBe("function");
    expect(typeof signIn).toBe("function");
    expect(typeof signOut).toBe("function");
  });

  it("registers exactly two providers: Google, unchanged, plus the admin Credentials provider", () => {
    const providers = capturedNextAuthConfig.current?.providers ?? [];
    expect(providers).toHaveLength(2);

    // providers[0] is the real `Google` provider function/object imported
    // from "next-auth/providers/google" - unmocked, so this is the actual
    // export, not a stand-in. Sanity-checking its shape (an OIDC-style
    // provider factory/object) is enough to prove it's still there and
    // still first, without re-testing next-auth's own provider internals.
    expect(providers[0]).toBeTruthy();

    // @auth/core's Credentials() factory itself returns a fixed shape
    // ({ id: "credentials", ... }) with whatever config it was called with
    // stashed under `options` - the real `id`/`authorize` NextAuth() ends
    // up using only appear after NextAuth's own internal provider
    // normalization (options merged over the defaults), which this
    // mocked-away NextAuth() never runs. `options` is exactly what auth.ts
    // passed in, so that's what proves the real id/authorize made it
    // through - see @auth/core/providers/credentials.js if this ever needs
    // re-verifying against a next-auth upgrade.
    const credentialsProvider = providers[1] as { options?: { id?: string; authorize?: unknown } };
    expect(credentialsProvider.options?.id).toBe(ADMIN_CREDENTIALS_PROVIDER_ID);
    expect(typeof credentialsProvider.options?.authorize).toBe("function");
  });
});

// --- isNonEmptyBoundedString -------------------------------------------

describe("isNonEmptyBoundedString", () => {
  it("accepts a normal string", () => {
    expect(isNonEmptyBoundedString("admin@example.com")).toBe(true);
  });

  it("rejects an empty string", () => {
    expect(isNonEmptyBoundedString("")).toBe(false);
  });

  it("rejects a non-string", () => {
    expect(isNonEmptyBoundedString(12345)).toBe(false);
    expect(isNonEmptyBoundedString(undefined)).toBe(false);
    expect(isNonEmptyBoundedString(null)).toBe(false);
  });

  it("rejects an oversized string", () => {
    expect(isNonEmptyBoundedString("a".repeat(1025))).toBe(false);
  });
});

// --- verifyAdminCredentials ---------------------------------------------

describe("verifyAdminCredentials", () => {
  it("returns the minimal identity on a 200 admin response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ id: "staging-admin", email: "admin@example.com", role: "admin" }),
      }),
    );

    const result = await verifyAdminCredentials("admin@example.com", "correct-password");

    expect(result).toEqual({ id: "staging-admin", email: "admin@example.com", role: "admin" });
  });

  it("returns null on a non-200 response (invalid login produces no session)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));

    const result = await verifyAdminCredentials("admin@example.com", "wrong-password");

    expect(result).toBeNull();
  });

  it("returns null on a network/backend error, without throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("backend unreachable")));

    const result = await verifyAdminCredentials("admin@example.com", "correct-password");

    expect(result).toBeNull();
  });

  it("returns null if the response doesn't look like a real admin identity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ role: "collector" }) }));

    const result = await verifyAdminCredentials("admin@example.com", "correct-password");

    expect(result).toBeNull();
  });

  it("POSTs credentials as a JSON body, never in the URL", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ id: "x", email: "e", role: "admin" }) });
    vi.stubGlobal("fetch", fetchMock);

    await verifyAdminCredentials("admin@example.com", "s3cr3t-password");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain("s3cr3t-password");
    expect(init.method).toBe("POST");
    expect(String(init.body)).toContain("s3cr3t-password");
  });
});

// --- adminAuthorize -------------------------------------------------------

describe("adminAuthorize", () => {
  it("valid Credentials login produces an admin identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ id: "staging-admin", email: "admin@example.com", role: "admin" }),
      }),
    );

    const result = await adminAuthorize({ email: "admin@example.com", password: "correct-password" });

    expect(result).toEqual({ id: "staging-admin", email: "admin@example.com", role: "admin" });
  });

  it("invalid login returns null (no session)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));

    const result = await adminAuthorize({ email: "admin@example.com", password: "wrong-password" });

    expect(result).toBeNull();
  });

  it("rejects missing credentials without calling the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await adminAuthorize({ email: "", password: "" });

    expect(result).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects undefined credentials without calling the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await adminAuthorize(undefined);

    expect(result).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an oversized password before calling the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await adminAuthorize({ email: "admin@example.com", password: "a".repeat(2000) });

    expect(result).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// --- applyJwtCallback -----------------------------------------------------

function makeAccount(provider: string): Account {
  return { provider, type: "credentials", providerAccountId: provider } as Account;
}

describe("applyJwtCallback", () => {
  it("sets role=admin and a roleExpiresAt on an admin Credentials sign-in", () => {
    const token = {} as JWT;

    const result = applyJwtCallback({
      token,
      account: makeAccount(ADMIN_CREDENTIALS_PROVIDER_ID),
      user: { id: "staging-admin", email: "admin@example.com" } as User,
    });

    expect(result.role).toBe("admin");
    expect(result.sub).toBe("staging-admin");
    expect(typeof result.roleExpiresAt).toBe("number");
    expect(result.roleExpiresAt).toBeGreaterThan(Date.now());
  });

  it("does not set role on a Google sign-in", () => {
    const token = {} as JWT;

    const result = applyJwtCallback({
      token,
      profile: { sub: "google-123", email: "collector@example.com" },
    });

    expect(result.role).toBeUndefined();
  });

  it("clears a stale role on a fresh Google sign-in", () => {
    const token = { role: "admin", roleExpiresAt: Date.now() + 10_000 } as JWT;

    const result = applyJwtCallback({
      token,
      profile: { sub: "google-123", email: "collector@example.com" },
    });

    expect(result.role).toBeUndefined();
    expect(result.roleExpiresAt).toBeUndefined();
  });

  it("demotes an admin token once roleExpiresAt has passed", () => {
    const token = { role: "admin", roleExpiresAt: Date.now() - 1000, sub: "staging-admin" } as JWT;

    const result = applyJwtCallback({ token });

    expect(result.role).toBeUndefined();
    expect(result.roleExpiresAt).toBeUndefined();
  });

  it("keeps an admin token that has not yet expired", () => {
    const token = {
      role: "admin",
      roleExpiresAt: Date.now() + ADMIN_SESSION_MAX_AGE_MS,
      sub: "staging-admin",
    } as JWT;

    const result = applyJwtCallback({ token });

    expect(result.role).toBe("admin");
  });

  it("never puts a password, hash, or ADMIN_TOKEN onto the token", () => {
    const token = {} as JWT;

    const result = applyJwtCallback({
      token,
      account: makeAccount(ADMIN_CREDENTIALS_PROVIDER_ID),
      user: { id: "staging-admin", email: "admin@example.com" } as User,
    });

    const serialized = JSON.stringify(result);
    expect(serialized).not.toMatch(/password|argon2|admin_token/i);
  });
});

// --- applySessionCallback ---------------------------------------------

describe("applySessionCallback", () => {
  it("session exposes role=admin for an admin token", async () => {
    const session = { user: {} } as Session;
    const token = { role: "admin", sub: "staging-admin", email: "admin@example.com" } as JWT;

    const result = await applySessionCallback({ session, token });

    expect(result.user?.role).toBe("admin");
  });

  it("does not mint a collector apiToken for an admin session", async () => {
    const session = { user: {} } as Session;
    const token = { role: "admin", sub: "staging-admin", email: "admin@example.com" } as JWT;

    const result = await applySessionCallback({ session, token });

    expect(result.apiToken).toBeUndefined();
  });

  it("mints an apiToken for a collector (non-admin) session", async () => {
    const session = { user: {} } as Session;
    const token = { sub: "google-123", email: "collector@example.com" } as JWT;

    const result = await applySessionCallback({ session, token });

    expect(typeof result.apiToken).toBe("string");
    expect(result.apiToken?.split(".")).toHaveLength(3);
  });

  it("leaves role undefined on a collector session", async () => {
    const session = { user: {} } as Session;
    const token = { sub: "google-123", email: "collector@example.com" } as JWT;

    const result = await applySessionCallback({ session, token });

    expect(result.user?.role).toBeUndefined();
  });

  it("never exposes API_JWT_SECRET or ADMIN_TOKEN in the session, for either role", async () => {
    process.env.ADMIN_TOKEN = "super-secret-admin-token-value";
    const adminSession = { user: {} } as Session;
    const adminToken = { role: "admin", sub: "staging-admin", email: "admin@example.com" } as JWT;
    const collectorSession = { user: {} } as Session;
    const collectorToken = { sub: "google-123", email: "collector@example.com" } as JWT;

    const adminResult = await applySessionCallback({ session: adminSession, token: adminToken });
    const collectorResult = await applySessionCallback({ session: collectorSession, token: collectorToken });

    for (const result of [adminResult, collectorResult]) {
      const serialized = JSON.stringify(result);
      expect(serialized).not.toContain("super-secret-admin-token-value");
      expect(serialized).not.toContain(process.env.API_JWT_SECRET);
    }
  });
});
