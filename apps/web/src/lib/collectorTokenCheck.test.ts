// @vitest-environment node
import { decodeJwt, jwtVerify } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/auth", () => ({ auth: vi.fn() }));

import {
  TOKEN_CHECK_CACHE_MS,
  TOKEN_CHECK_FAILURE_CACHE_MS,
  TOKEN_CHECK_LIMIT,
  TOKEN_CHECK_WINDOW_MS,
  cachedCollectorTokenCheck,
  checkCollectorToken,
  resetTokenCheckState,
  tokenCheckClientKey,
  tokenCheckRetryAfter,
} from "./collectorTokenCheck";
import { GET } from "@/app/api/collector-token-check/route";

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
  resetTokenCheckState();
  vi.useRealTimers();
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

describe("cachedCollectorTokenCheck", () => {
  it("calls the API at most once per 60 s, and concurrent callers share the call", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    const answers = await Promise.all([cachedCollectorTokenCheck(), cachedCollectorTokenCheck(), cachedCollectorTokenCheck()]);
    expect(answers).toEqual(["ok", "ok", "ok"]);
    expect(await cachedCollectorTokenCheck()).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(TOKEN_CHECK_CACHE_MS - 1);
    await cachedCollectorTokenCheck();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(2);
    fetchMock.mockImplementation(apiVerifying("railway-copy-that-diverged"));
    expect(await cachedCollectorTokenCheck()).toBe("mismatch");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("cachedCollectorTokenCheck failures", () => {
  it("keeps a failed answer only for TOKEN_CHECK_FAILURE_CACHE_MS", async () => {
    vi.useFakeTimers();
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    expect(await cachedCollectorTokenCheck()).toBe("unreachable");
    expect(await cachedCollectorTokenCheck()).toBe("unreachable");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(TOKEN_CHECK_FAILURE_CACHE_MS + 1);
    fetchMock.mockReset();
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    expect(await cachedCollectorTokenCheck()).toBe("ok");
  });
});

describe("token check rate limit", () => {
  it("allows TOKEN_CHECK_LIMIT requests per client per window, then gives a bounded Retry-After", () => {
    const now = 5 * TOKEN_CHECK_WINDOW_MS + 1_000;
    for (let i = 0; i < TOKEN_CHECK_LIMIT; i++) expect(tokenCheckRetryAfter("203.0.113.9", now)).toBeNull();
    const retry = tokenCheckRetryAfter("203.0.113.9", now);
    expect(retry).toBeGreaterThan(0);
    expect(retry).toBeLessThanOrEqual(TOKEN_CHECK_WINDOW_MS / 1000);
    // Another client, and the next window, start fresh.
    expect(tokenCheckRetryAfter("198.51.100.4", now)).toBeNull();
    expect(tokenCheckRetryAfter("203.0.113.9", now + TOKEN_CHECK_WINDOW_MS)).toBeNull();
  });

  it("keys by the first X-Forwarded-For hop", () => {
    expect(tokenCheckClientKey(new Headers({ "x-forwarded-for": "203.0.113.9, 10.0.0.1" }))).toBe("203.0.113.9");
    expect(tokenCheckClientKey(new Headers({ "x-real-ip": "198.51.100.4" }))).toBe("198.51.100.4");
    expect(tokenCheckClientKey(new Headers())).toBe("unknown");
  });
});

describe("GET /api/collector-token-check", () => {
  const request = (ip: string) => new Request("http://web.test/api/collector-token-check", { headers: { "x-forwarded-for": ip } });

  it("answers the verifier's one word, uncached by browsers, and reuses it", async () => {
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    const response = await GET(request("192.0.2.1"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
    expect(response.headers.get("cache-control")).toBe("no-store");
    await GET(request("192.0.2.2"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refuses a flood from one client with 429 and Retry-After, without calling the API", async () => {
    fetchMock.mockImplementation(apiVerifying(WEB_SECRET));
    for (let i = 0; i < TOKEN_CHECK_LIMIT; i++) await GET(request("192.0.2.7"));
    const response = await GET(request("192.0.2.7"));
    expect(response.status).toBe(429);
    expect(Number(response.headers.get("retry-after"))).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
