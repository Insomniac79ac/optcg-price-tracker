import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { track } = vi.hoisted(() => ({ track: vi.fn() }));
vi.mock("@vercel/analytics", () => ({ track }));

import {
  ANALYTICS_EVENTS,
  sanitizeAnalyticsProperties,
  scrubAnalyticsEvent,
  trackEvent,
  type AnalyticsEventName,
} from "./analytics";

const ORIGINAL = process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS;

beforeEach(() => {
  track.mockClear();
  process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS = "1";
});
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS;
  else process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS = ORIGINAL;
});

describe("event names (plan §F2)", () => {
  it("are exactly the nine planned events", () => {
    expect([...ANALYTICS_EVENTS]).toEqual([
      "sign_in_started",
      "sign_in_completed",
      "collection_add",
      "collection_remove",
      "watch_add",
      "watch_remove",
      "account_export",
      "account_delete",
      "share_card",
    ]);
  });

  it("drops an event that is not on the list", () => {
    trackEvent("page_scrolled" as AnalyticsEventName, { page_type: "home" });
    expect(track).not.toHaveBeenCalled();
  });
});

describe("payload allowlist (no personal data)", () => {
  it("sends only page type and release code, even when a caller passes personal data", () => {
    trackEvent("collection_add", {
      page_type: "card",
      release_code: "OP-01",
      // Everything below must never leave the browser.
      ...({
        user_id: 42,
        userId: "42",
        email: "collector@example.com",
        quantity: 3,
        paid_jpy_per_card: 1200,
        price_paid: 1200,
        name: "Someone",
        card_print_id: 5661,
      } as object),
    });
    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("collection_add", { page_type: "card", release_code: "OP-01" });
  });

  it.each([
    ["an unknown page type", { page_type: "admin" }],
    ["an email smuggled as a release code", { release_code: "a@b.co" }],
    ["a number as a release code", { release_code: 101 }],
    ["a lower-case code", { release_code: "op-01" }],
    ["a code with a card number", { release_code: "OP01-001" }],
  ])("drops %s", (_label, properties) => {
    expect(sanitizeAnalyticsProperties(properties)).toEqual({});
  });

  it.each(["OP-01", "EB-04", "PRB-02", "ST-36"])("keeps the official code %s", (code) => {
    expect(sanitizeAnalyticsProperties({ release_code: code })).toEqual({ release_code: code });
  });

  it("returns an empty payload for junk input", () => {
    expect(sanitizeAnalyticsProperties(null)).toEqual({});
    expect(sanitizeAnalyticsProperties("x")).toEqual({});
  });

  it("is a no-op while analytics is not switched on", () => {
    delete process.env.NEXT_PUBLIC_VERCEL_WEB_ANALYTICS;
    trackEvent("watch_add", { page_type: "card" });
    expect(track).not.toHaveBeenCalled();
  });
});

describe("page view scrubbing", () => {
  it("strips query strings and fragments", () => {
    expect(
      scrubAnalyticsEvent({ type: "pageview", url: "https://x.app/sign-in?callbackUrl=%2Fcollection&email=a%40b.co#top" }),
    ).toEqual({ type: "pageview", url: "https://x.app/sign-in" });
  });

  it.each(["https://x.app/admin", "https://x.app/admin/cache", "https://x.app/api/admin/release-status"])(
    "does not send %s",
    (url) => {
      expect(scrubAnalyticsEvent({ type: "pageview", url })).toBeNull();
    },
  );

  it("keeps public paths, including /administrative-looking card paths that are not /admin", () => {
    expect(scrubAnalyticsEvent({ type: "event", url: "https://x.app/prints/5661" })).toEqual({
      type: "event",
      url: "https://x.app/prints/5661",
    });
  });

  it("drops an unparsable URL", () => {
    expect(scrubAnalyticsEvent({ type: "pageview", url: "not a url" })).toBeNull();
  });
});

describe("call sites", () => {
  it("only src/lib/analytics.ts imports the Vercel track() API", () => {
    const root = path.resolve(__dirname, "..");
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = path.join(dir, entry);
        if (statSync(full).isDirectory()) walk(full);
        else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
          const source = readFileSync(full, "utf8");
          if (/from "@vercel\/analytics"/.test(source) && !full.endsWith(path.join("lib", "analytics.ts"))) {
            offenders.push(path.relative(root, full));
          }
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});
