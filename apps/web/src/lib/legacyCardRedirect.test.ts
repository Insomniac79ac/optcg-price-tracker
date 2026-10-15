// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { isLegacyCardId, legacyCardRedirectPath, readLegacyCardDestination } from "./legacyCardRedirect";

const base = { card_id: 7, card_code: "OP01-001" };

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("legacyCardRedirectPath (exact, unique only)", () => {
  it("names the print only for an exact, unique destination", () => {
    expect(legacyCardRedirectPath({ ...base, card_print_id: 42, resolution: "exact" })).toBe("/prints/42");
  });

  it.each([
    ["two prints", { ...base, card_print_id: null, resolution: "multiple_prints" as const }],
    ["no print", { ...base, card_print_id: null, resolution: "no_print" as const }],
    // Defensive: a print id without an exact resolution is never trusted.
    ["print id on a non-exact answer", { ...base, card_print_id: 42, resolution: "multiple_prints" as const }],
    ["exact without a print id", { ...base, card_print_id: null, resolution: "exact" as const }],
    ["exact with a zero id", { ...base, card_print_id: 0, resolution: "exact" as const }],
    ["exact with a fractional id", { ...base, card_print_id: 4.2, resolution: "exact" as const }],
  ])("falls back to the code's version chooser for %s", (_label, destination) => {
    expect(legacyCardRedirectPath(destination)).toBe("/cards/code/OP01-001");
  });

  it("encodes the card code as one path segment", () => {
    expect(legacyCardRedirectPath({ card_id: 1, card_code: "P-001/x", card_print_id: null, resolution: "no_print" }))
      .toBe("/cards/code/P-001%2Fx");
  });

  it("has nowhere to go without a card code", () => {
    expect(legacyCardRedirectPath({ card_id: 1, card_code: "  ", card_print_id: null, resolution: "no_print" })).toBeNull();
  });
});

describe("isLegacyCardId", () => {
  it.each(["1", "25", "1234567890"])("accepts %s", (id) => expect(isLegacyCardId(id)).toBe(true));
  it.each(["0", "01", "-1", "1.5", "abc", "1e3", "", "12345678901"])("rejects %s", (id) => expect(isLegacyCardId(id)).toBe(false));
});

describe("readLegacyCardDestination", () => {
  function stub(status: number, body?: unknown) {
    const fetchMock = vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("calls the public lookup without credentials", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchMock = stub(200, { ...base, card_print_id: 42, resolution: "exact" });
    const result = await readLegacyCardDestination("7");
    expect(result).toEqual({ kind: "found", destination: { ...base, card_print_id: 42, resolution: "exact" } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/cards\/7\/print-destination$/);
    expect(init.headers).toBeUndefined();
  });

  it("does not call the API for an id that is not a legacy card id", async () => {
    const fetchMock = stub(200, {});
    expect(await readLegacyCardDestination("../me")).toEqual({ kind: "not_found" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps 404 to not found", async () => {
    stub(404, { detail: "Card not found" });
    expect(await readLegacyCardDestination("9")).toEqual({ kind: "not_found" });
  });

  it.each([
    ["a server error", () => stub(503, { detail: "down" })],
    ["an answer for another card", () => stub(200, { ...base, card_id: 8, card_print_id: 1, resolution: "exact" })],
    ["a malformed answer", () => stub(200, { card_id: 7 })],
    ["a network failure", () => vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }))],
  ])("reports %s as unavailable, never as a destination", async (_label, arrange) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    arrange();
    expect(await readLegacyCardDestination("7")).toEqual({ kind: "unavailable" });
  });
});
