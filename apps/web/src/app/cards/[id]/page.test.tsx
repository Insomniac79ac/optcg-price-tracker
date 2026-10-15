// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const { readLegacyCardDestination } = vi.hoisted(() => ({ readLegacyCardDestination: vi.fn() }));
vi.mock("@/lib/legacyCardRedirect", async () => {
  const actual = await vi.importActual<typeof import("@/lib/legacyCardRedirect")>("@/lib/legacyCardRedirect");
  return { ...actual, readLegacyCardDestination };
});
vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  permanentRedirect: (url: string) => { throw new Error(`NEXT_REDIRECT 308 ${url}`); },
  redirect: (url: string) => { throw new Error(`NEXT_REDIRECT 307 ${url}`); },
}));

import LegacyCardPage from "./page";

const visit = (id: string) => LegacyCardPage({ params: Promise.resolve({ id }) });
const found = (card_print_id: number | null, resolution: string, card_code = "OP01-001") => ({
  kind: "found",
  destination: { card_id: 7, card_code, card_print_id, resolution },
});

describe("/cards/[id] retirement (PLAN E1)", () => {
  beforeEach(() => readLegacyCardDestination.mockReset());

  it("308s an exact, unique legacy card to its print page", async () => {
    readLegacyCardDestination.mockResolvedValue(found(42, "exact"));
    await expect(visit("7")).rejects.toThrow("NEXT_REDIRECT 308 /prints/42");
    expect(readLegacyCardDestination).toHaveBeenCalledWith("7");
  });

  it.each(["multiple_prints", "no_print"])("308s a %s legacy card to its card-code chooser", async (resolution) => {
    readLegacyCardDestination.mockResolvedValue(found(null, resolution));
    await expect(visit("7")).rejects.toThrow("NEXT_REDIRECT 308 /cards/code/OP01-001");
  });

  it("answers 404 for an unknown id", async () => {
    readLegacyCardDestination.mockResolvedValue({ kind: "not_found" });
    await expect(visit("999")).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("answers 404 when there is not even a card code", async () => {
    readLegacyCardDestination.mockResolvedValue(found(null, "no_print", ""));
    await expect(visit("7")).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("never redirects when the lookup fails", async () => {
    readLegacyCardDestination.mockResolvedValue({ kind: "unavailable" });
    await expect(visit("7")).rejects.toThrow("Legacy card lookup unavailable");
  });

  it("never uses a temporary redirect", async () => {
    readLegacyCardDestination.mockResolvedValue(found(42, "exact"));
    await expect(visit("7")).rejects.not.toThrow(/NEXT_REDIRECT 307/);
  });
});
