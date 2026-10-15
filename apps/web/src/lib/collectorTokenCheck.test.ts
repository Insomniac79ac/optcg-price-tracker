// @vitest-environment node
import { decodeJwt, jwtVerify } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/auth", () => ({ auth: vi.fn() }));

import { checkCollectorToken } from "./collectorTokenCheck";

const WEB_SECRET = "website-copy-of-api-jwt-secret";
const fetchMock = vi.fn();

/** A stand-in for services/api/app/auth.py's require_current_user: same
 * signature check, same claim check, same two details. */
function apiVerifying(apiSecret: string) {
  return async (_url: string, init: RequestInit) => {
    const token = String((init.headers as Record<string, string>).Authorization).replace("Bearer ", "");
    try {
      await jwtVerify(token, new TextEncoder().encode(apiSecret), { algorithms: ["HS256"] });
    } catch {
      return Response.json({ detail: "Invalid or expired token" }, { status: 401 });
    }
    const claims = decodeJwt(token);
    if (!claims.sub || !claims.email) return Response.json({ detail: "Token missing required claims" }, { status: 401 });
    return Response.json({ email: claims.email }, { status: 200 });
  };
}

beforeEach(() => {
  vi.stubEnv("API_JWT_SECRET", WEB_SECRET);
  vi.stubEnv("API_INTERNAL_URL", "http://api.test");
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("checkCollectorToken", () => {
  it("reports a mismatch when the API holds a different API_JWT_SECRET (the 2026-10-15 /account failure)", async () => {
    fetchMock.mockImplementation(apiVerifying("railway-copy-that-diverged"));
    expect(await checkCollectorToken()).toBe("mismatch");
  });

  it("reports ok when the API accepts the website's signature", async () => {
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    expect(await checkCollectorToken()).toBe("ok");
  });

  it("sends a pass that cannot open or create an account: no email, short-lived", async () => {
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    await checkCollectorToken();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/me\/profile$/);
    const claims = decodeJwt(String(init.headers.Authorization).replace("Bearer ", ""));
    expect(claims.email).toBeUndefined();
    expect(claims.sub).toBe("collector-token-check");
    expect(claims.exp! - claims.iat!).toBeLessThanOrEqual(60);
  });

  it.each([
    ["disabled", () => Response.json({ detail: "Not Found" }, { status: 404 })],
    ["unexpected", () => Response.json({ detail: "API_JWT_SECRET is not configured" }, { status: 500 })],
    ["unexpected", () => Response.json({ email: "x" }, { status: 200 })],
  ])("reports %s for other API answers", async (status, answer) => {
    fetchMock.mockImplementation(async () => answer());
    expect(await checkCollectorToken()).toBe(status);
  });

  it("reports unreachable when the API cannot be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    expect(await checkCollectorToken()).toBe("unreachable");
  });

  it("reports unconfigured without calling the API when the website has no secret", async () => {
    vi.stubEnv("API_JWT_SECRET", "");
    expect(await checkCollectorToken()).toBe("unconfigured");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
