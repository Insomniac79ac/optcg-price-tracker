import { beforeEach, describe, expect, it, vi } from "vitest";

const { authMock, redirectMock, notFoundMock } = vi.hoisted(() => ({
  authMock: vi.fn(),
  redirectMock: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
  notFoundMock: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

vi.mock("@/lib/auth", () => ({ auth: authMock }));
vi.mock("next/navigation", () => ({ redirect: redirectMock, notFound: notFoundMock }));
// The real `server-only` package throws whenever `window` exists - true
// under this project's default jsdom test environment even though this is
// plainly a server-side unit test, not a rendered component. Stub it out
// rather than fight the environment.
vi.mock("server-only", () => ({}));

import { getAdminIdentityForRouteHandler, requireAdminSession } from "./adminSession";

beforeEach(() => {
  authMock.mockReset();
  redirectMock.mockClear();
  notFoundMock.mockClear();
});

describe("requireAdminSession", () => {
  it("returns the identity for a valid admin session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "staging-admin", email: "admin@example.com", role: "admin" },
    });

    const identity = await requireAdminSession();

    expect(identity).toEqual({ id: "staging-admin", email: "admin@example.com" });
    expect(redirectMock).not.toHaveBeenCalled();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("redirects a signed-out visitor to /admin/login", async () => {
    authMock.mockResolvedValueOnce(null);

    await expect(requireAdminSession()).rejects.toThrow("NEXT_REDIRECT:/admin/login");
  });

  it("returns not-found for a signed-in collector session (role !== admin)", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "google-123", email: "collector@example.com" },
    });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("returns not-found (not a redirect) for a session with an unexpected role value", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "x", email: "someone@example.com", role: "superadmin" },
    });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("treats a role=admin session missing an email as not-admin (defensive)", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "staging-admin", role: "admin" } });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("never reads role from anything other than auth()'s own session - takes no request/header argument at all", () => {
    expect(requireAdminSession).toHaveLength(0);
  });
});

describe("getAdminIdentityForRouteHandler", () => {
  it("returns the identity for a valid admin session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "staging-admin", email: "admin@example.com", role: "admin" },
    });

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toEqual({ id: "staging-admin", email: "admin@example.com" });
  });

  it("returns null (never throws/redirects) for a signed-out request", async () => {
    authMock.mockResolvedValueOnce(null);

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toBeNull();
    expect(redirectMock).not.toHaveBeenCalled();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("returns null for a signed-in collector session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "google-123", email: "collector@example.com" },
    });

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toBeNull();
  });
});
