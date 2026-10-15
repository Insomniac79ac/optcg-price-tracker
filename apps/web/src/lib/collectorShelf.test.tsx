import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSession } = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("next-auth/react", () => ({ useSession }));

import { heldByPrint, useCollectorShelf, watchedByPrint } from "./collectorShelf";

const COLLECTOR = { data: { user: { email: "c@example.test" }, sessionKind: "collector" }, status: "authenticated" };

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

describe("heldByPrint / watchedByPrint", () => {
  it("counts only exact entries, never an unresolved one", () => {
    const held = heldByPrint([
      { id: 1, card_print_id: 5, resolution: "exact", quantity: 2, paid_jpy_per_card: 300, acquired_on: null },
      { id: 2, card_print_id: null, resolution: "unresolved", quantity: 4, paid_jpy_per_card: null, acquired_on: null },
    ]);
    expect([...held.entries()]).toEqual([[5, { entryId: 1, quantity: 2, paidJpyPerCard: 300, acquiredOn: null }]]);
    const watched = watchedByPrint([
      { id: 3, card_print_id: 6, resolution: "exact", target_jpy: 900 },
      { id: 4, card_print_id: null, resolution: "unresolved", target_jpy: 100 },
    ]);
    expect([...watched.entries()]).toEqual([[6, { entryId: 3, targetJpy: 900 }]]);
  });
});

describe("useCollectorShelf", () => {
  it.each([
    ["signed out", { data: null, status: "unauthenticated" }],
    ["an admin session", { data: { user: { role: "admin" }, sessionKind: "admin" }, status: "authenticated" }],
    ["an expired admin session", { data: { user: {}, sessionKind: "admin", adminSessionExpired: true }, status: "authenticated" }],
  ])("makes no request for %s", async (_label, session) => {
    useSession.mockReturnValue(session);
    const { result } = renderHook(() => useCollectorShelf());
    await waitFor(() => expect(result.current.status).toBe("visitor"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stays loading while the session resolves", () => {
    useSession.mockReturnValue({ data: null, status: "loading" });
    const { result } = renderHook(() => useCollectorShelf());
    expect(result.current.status).toBe("loading");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads the collection and watchlist through the same-origin route", async () => {
    useSession.mockReturnValue(COLLECTOR);
    fetchMock.mockImplementation(async (url: string) =>
      url === "/api/me/collection"
        ? json(200, { entries: [{ id: 1, card_print_id: 5, resolution: "exact", quantity: 2, paid_jpy_per_card: null, acquired_on: null }] })
        : json(200, { entries: [{ id: 3, card_print_id: 6, resolution: "exact", target_jpy: null }] }));
    const { result } = renderHook(() => useCollectorShelf());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.held.get(5)?.quantity).toBe(2);
    expect(result.current.watched.get(6)?.targetJpy).toBeNull();
    for (const [, init] of fetchMock.mock.calls as [string, RequestInit][]) {
      expect(init.credentials).toBe("same-origin");
      expect(new Headers(init.headers).has("authorization")).toBe(false);
    }
  });

  it("treats a 404 as accounts switched off", async () => {
    useSession.mockReturnValue(COLLECTOR);
    fetchMock.mockResolvedValue(json(404, { detail: "Not Found" }));
    const { result } = renderHook(() => useCollectorShelf());
    await waitFor(() => expect(result.current.status).toBe("disabled"));
  });

  it("treats any other failure as an error, never as an empty collection", async () => {
    useSession.mockReturnValue(COLLECTOR);
    fetchMock.mockResolvedValue(json(502, { error: "Failed to reach backend API" }));
    const { result } = renderHook(() => useCollectorShelf());
    await waitFor(() => expect(result.current.status).toBe("error"));
  });
});
