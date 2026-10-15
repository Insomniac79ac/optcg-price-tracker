import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { mintApiToken } = vi.hoisted(() => ({ mintApiToken: vi.fn() }));
vi.mock("@/lib/collectorApi", () => ({ API_INTERNAL_URL: "http://api.test", mintApiToken }));

import { loadAccountOverview, logAccountUpstreamFailure } from "./accountServer";

const IDENTITY = { sub: "google-sub-123", email: "collector@example.test", name: "Test Collector" };
const TOKEN = "secret.bearer.token";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

let errors: string[];

beforeEach(() => {
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    errors.push(args.map(String).join(" "));
  });
  mintApiToken.mockResolvedValue(TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function expectNoPrivateData() {
  const all = errors.join("\n");
  expect(all).not.toContain(TOKEN);
  expect(all).not.toContain(IDENTITY.email);
  expect(all).not.toContain(IDENTITY.sub);
  expect(all).not.toContain("Test Collector");
}

describe("loadAccountOverview upstream logging", () => {
  it("logs nothing when both reads succeed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.endsWith("/profile")
        ? json(200, { email: IDENTITY.email, name: "Test Collector", member_since: "2026-10-15T00:00:00Z" })
        : json(200, { currency: "JPY", collection_visibility: "private" })));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview.state).toBe("ok");
    expect(errors).toEqual([]);
  });

  it("logs the step and status of a failed read, never the token or identity", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.endsWith("/profile") ? json(401, { detail: `bad token ${TOKEN} for ${IDENTITY.email}` }) : json(200, {})));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview.state).toBe("error");
    expect(errors).toEqual(["[account] GET /me/profile failed status=401"]);
    expectNoPrivateData();
  });

  it("does not log the accounts-disabled 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(404, { detail: "Not Found" })));
    expect((await loadAccountOverview(IDENTITY)).state).toBe("disabled");
    expect(errors).toEqual([]);
  });

  it("logs a network failure by error class only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      const error = new Error(`connect ECONNREFUSED with ${TOKEN}`);
      error.name = "TypeError";
      throw error;
    }));
    expect((await loadAccountOverview(IDENTITY)).state).toBe("error");
    expect(errors).toContain("[account] GET /me/profile failed error=TypeError");
    expectNoPrivateData();
  });

  it("logs a token-minting failure by error class only", async () => {
    mintApiToken.mockRejectedValue(new RangeError(`API_JWT_SECRET ${TOKEN}`));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect((await loadAccountOverview(IDENTITY)).state).toBe("error");
    expect(errors).toEqual(["[account] mint API token failed error=RangeError"]);
    expect(fetchMock).not.toHaveBeenCalled();
    expectNoPrivateData();
  });
});

describe("logAccountUpstreamFailure", () => {
  it("never echoes an arbitrary error name", () => {
    const error = new Error("x");
    error.name = "Bearer abc.def collector@example.test";
    logAccountUpstreamFailure("GET /me/profile", { error });
    expect(errors).toEqual(["[account] GET /me/profile failed error=unknown"]);
  });
});
