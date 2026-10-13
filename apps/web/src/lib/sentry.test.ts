import { PHASE_PRODUCTION_SERVER } from "next/constants";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { init, captureRequestError, captureException, httpIntegration } = vi.hoisted(() => ({
  httpIntegration: vi.fn((options: object) => ({ name: "Http", options })),
  init: vi.fn(),
  captureRequestError: vi.fn(),
  captureException: vi.fn(),
}));
vi.mock("@sentry/nextjs", () => ({ init, captureRequestError, captureException, httpIntegration }));

import { buildCommit } from "@/generated/buildVersion";

import { sentryIngestOrigin } from "./cspSentryOrigin";
import { scrubSentryEvent, sentryOptions, withoutSessionTracking } from "./sentry";

const DSN = "https://publickey@o123.ingest.us.sentry.io/456";
const ENV_KEYS = ["NEXT_PUBLIC_SENTRY_DSN", "NEXT_PUBLIC_APP_ENV"] as const;
const saved: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const key of ENV_KEYS) saved[key] = process.env[key];
  for (const key of ENV_KEYS) delete process.env[key];
  init.mockClear();
  captureRequestError.mockClear();
  captureException.mockClear();
  vi.resetModules();
});
afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
});

describe("scrubSentryEvent (beforeSend)", () => {
  it("removes Authorization, cookies, request bodies, query strings and the user", () => {
    const event = scrubSentryEvent({
      request: {
        url: "https://x.app/api/auth/callback/google?code=4/abc&state=xyz",
        query_string: "code=4/abc&state=xyz",
        cookies: { "authjs.session-token": "secret" },
        data: { email: "a@b.co" },
        headers: {
          Authorization: "Bearer eyJhbGciOi",
          authorization: "Bearer lower",
          Cookie: "authjs.session-token=secret",
          "Set-Cookie": "a=b",
          "X-Admin-Token": "admin",
          "Proxy-Authorization": "Basic x",
          "User-Agent": "Mozilla/5.0",
        },
      },
      user: { id: "42", email: "a@b.co", ip_address: "1.2.3.4" },
      breadcrumbs: [
        { data: { url: "/api/me/collection?token=t", method: "GET" } },
        { data: { from: "/sign-in?callbackUrl=%2Fcollection", to: "/collection#x" } },
        { message: "no data" },
      ],
    });

    expect(event.request).toEqual({
      url: "https://x.app/api/auth/callback/google",
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    expect(event).not.toHaveProperty("user");
    expect(event.breadcrumbs).toEqual([
      { data: { url: "/api/me/collection", method: "GET" } },
      { data: { from: "/sign-in", to: "/collection" } },
      { message: "no data" },
    ]);
    expect(JSON.stringify(event)).not.toMatch(/secret|Bearer|a@b\.co|code=|eyJ/);
  });

  it("accepts an event with no request or breadcrumbs", () => {
    expect(scrubSentryEvent({})).toEqual({});
  });
});

describe("withoutSessionTracking", () => {
  it("drops only the per-page-view session integration", () => {
    const defaults = [{ name: "BrowserSession" }, { name: "GlobalHandlers" }, { name: "Dedupe" }];
    expect(withoutSessionTracking(defaults).map((i) => i.name)).toEqual(["GlobalHandlers", "Dedupe"]);
  });
});

describe("sentryOptions", () => {
  it("never sends default PII, traces or replays, and tags staging with the build SHA", () => {
    const options = sentryOptions(DSN);
    expect(options).toEqual({
      dsn: DSN,
      environment: "staging",
      release: buildCommit,
      sendDefaultPii: false,
      tracesSampleRate: 0,
      beforeSend: scrubSentryEvent,
      integrations: withoutSessionTracking,
    });
    expect(options).not.toHaveProperty("replaysSessionSampleRate");
    expect(options).not.toHaveProperty("replaysOnErrorSampleRate");
  });

  it("uses NEXT_PUBLIC_APP_ENV as the environment when it is set", () => {
    process.env.NEXT_PUBLIC_APP_ENV = "staging";
    expect(sentryOptions(DSN).environment).toBe("staging");
  });
});

describe("no-op without NEXT_PUBLIC_SENTRY_DSN", () => {
  it("server register() and onRequestError do not touch the SDK", async () => {
    const { register, onRequestError } = await import("../instrumentation");
    await register();
    await onRequestError(new Error("x"), { path: "/", method: "GET", headers: {} }, {
      routerKind: "App Router",
      routePath: "/",
      routeType: "render",
      renderSource: "react-server-components",
      revalidateReason: undefined,
    } as never);
    expect(init).not.toHaveBeenCalled();
    expect(captureRequestError).not.toHaveBeenCalled();
  });

  it("browser instrumentation does not initialise the SDK", async () => {
    await import("../instrumentation-client");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(init).not.toHaveBeenCalled();
  });

  it("error boundaries report nothing", async () => {
    const { reportError } = await import("./reportError");
    reportError(new Error("x"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(captureException).not.toHaveBeenCalled();
  });

  it("leaves CSP connect-src unchanged", () => {
    expect(sentryIngestOrigin(undefined)).toBeNull();
    expect(sentryIngestOrigin("  ")).toBeNull();
  });
});

describe("with NEXT_PUBLIC_SENTRY_DSN", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = DSN;
  });

  it("server register() initialises with the scrubbing options", async () => {
    const { register } = await import("../instrumentation");
    await register();
    expect(init).toHaveBeenCalledTimes(1);
    const options = init.mock.calls[0][0];
    expect(options).toMatchObject({ dsn: DSN, sendDefaultPii: false, tracesSampleRate: 0 });
    // The module registry was reset, so compare behaviour, not identity.
    expect(options.beforeSend({ request: { headers: { Authorization: "Bearer x" } } })).toEqual({ request: { headers: {} } });
    // Incoming requests are not tracked as release-health sessions.
    const integrations = options.integrations([{ name: "Http" }, { name: "OnUncaughtException" }]);
    expect(integrations).toEqual([{ name: "OnUncaughtException" }, { name: "Http", options: { trackIncomingRequestsAsSessions: false } }]);
  });

  it("browser instrumentation initialises with the same options", async () => {
    await import("../instrumentation-client");
    await vi.waitFor(() => expect(init).toHaveBeenCalledTimes(1));
    expect(init.mock.calls[0][0]).toMatchObject({ dsn: DSN, sendDefaultPii: false, tracesSampleRate: 0 });
  });

  it("error boundaries report the error", async () => {
    const { reportError } = await import("./reportError");
    const error = new Error("boom");
    reportError(error);
    await vi.waitFor(() => expect(captureException).toHaveBeenCalledWith(error));
  });

  it("allows only the ingest origin in CSP, without the public key", async () => {
    expect(sentryIngestOrigin(DSN)).toBe("https://o123.ingest.us.sentry.io");
    const { default: loadConfig } = await import("../../next.config");
    const headers = await loadConfig(PHASE_PRODUCTION_SERVER).headers!();
    const csp = headers[0].headers.find((h) => h.key === "Content-Security-Policy")!.value;
    const connect = csp.split("; ").find((d) => d.startsWith("connect-src"))!;
    expect(connect).toContain("https://o123.ingest.us.sentry.io");
    expect(csp).not.toContain("publickey");
  });

  it("rejects a non-https DSN", () => {
    expect(() => sentryIngestOrigin("http://k@o1.ingest.sentry.io/1")).toThrow(/https/);
    expect(() => sentryIngestOrigin("not a url")).toThrow();
  });
});
