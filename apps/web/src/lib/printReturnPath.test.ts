import { describe, expect, it } from "vitest";

import { printSignInCallbackPath, printSignInHref, signedOutPrintSignInHref, type UntrustedPrintRequest } from "./printReturnPath";

const EVIL: UntrustedPrintRequest = {
  url: "https://evil.example/prints/2615?callbackUrl=https://evil.example&next=https://evil.example/phish",
  searchParams: {
    callbackUrl: "https://evil.example",
    next: "https://evil.example/phish",
  },
  headers: {
    host: "evil.example",
    "x-forwarded-host": "evil.example",
    "x-forwarded-proto": "https",
    "x-forwarded-uri": "https://evil.example/prints/2615",
    "x-forwarded-for": "203.0.113.5",
  },
};

function expectPrintReturn(href: string, routeId: string) {
  expect(href.startsWith("/")).toBe(true);
  expect(href.startsWith("//")).toBe(false);
  expect(href).not.toContain("evil.example");
  expect(href).not.toContain("http");
  const page = new URL(href, "https://staging.cardpirate.app");
  expect(page.origin).toBe("https://staging.cardpirate.app");
  expect(page.pathname).toBe("/sign-in");
  const callback = page.searchParams.get("callbackUrl");
  expect(callback).toBe(`/prints/${routeId}`);
  expect(callback?.startsWith("/")).toBe(true);
  expect(callback?.startsWith("//")).toBe(false);
  const back = new URL(callback ?? "", "https://staging.cardpirate.app");
  expect(back.origin).toBe("https://staging.cardpirate.app");
  expect(back.pathname).toBe(`/prints/${routeId}`);
  expect(back.search).toBe("");
}

describe("print sign-in callback", () => {
  it("builds the callback only from the route id, as a same-origin relative path", () => {
    expect(printSignInCallbackPath("2615")).toBe("/prints/2615");
    expect(printSignInHref("2615")).toBe("/sign-in?callbackUrl=%2Fprints%2F2615");
    expectPrintReturn(printSignInHref("2615")!, "2615");
  });

  it("ignores a crafted callbackUrl, next, Host, and x-forwarded-* input", () => {
    expect(printSignInCallbackPath("2615", EVIL)).toBe("/prints/2615");
    expect(printSignInHref("2615", EVIL)).toBe("/sign-in?callbackUrl=%2Fprints%2F2615");
    expectPrintReturn(printSignInHref("2615", EVIL)!, "2615");
    expect(signedOutPrintSignInHref("2615", null, EVIL)).toBe("/sign-in?callbackUrl=%2Fprints%2F2615");
    expect(signedOutPrintSignInHref("2615", { sessionKind: "admin" }, EVIL)).toBe("/sign-in?callbackUrl=%2Fprints%2F2615");
  });

  it("does not turn the route id itself into an open redirect", () => {
    for (const routeId of [
      "https://evil.example",
      "//evil.example",
      "/prints/2615",
      "2615?callbackUrl=https://evil.example",
      "2615&next=https://evil.example",
      "../2615",
      "2615/../admin",
      "2615\\evil",
      "",
      "02615 ",
    ]) {
      expect(printSignInHref(routeId, EVIL)).toBeNull();
    }
  });

  it("hides the link for a collector and still ignores the request", () => {
    expect(signedOutPrintSignInHref("2615", { sessionKind: "collector" }, EVIL)).toBeNull();
    expect(signedOutPrintSignInHref("2615", { sessionKind: null }, EVIL)).toBe("/sign-in?callbackUrl=%2Fprints%2F2615");
  });
});
