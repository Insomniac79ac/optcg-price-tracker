import { afterEach, describe, expect, it, vi } from "vitest";

import { updateMappingCompatibilityCard } from "./api";

describe("updateMappingCompatibilityCard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the PATCH compatibility-card endpoint without approve or print identity fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pricing_identity_changed: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateMappingCompatibilityCard(17, 42, "Compatibility metadata only");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/admin/source-mappings/17/compatibility-card");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({
      compatibility_card_id: 42,
      review_notes: "Compatibility metadata only",
    });
    expect(body).not.toHaveProperty("approve");
    expect(body).not.toHaveProperty("card_print_id");
  });

  it("supports clearing compatibility metadata with an explicit null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pricing_identity_changed: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateMappingCompatibilityCard(18, null);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      compatibility_card_id: null,
      review_notes: null,
    });
  });

  it("surfaces the backend compatibility validation message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "legacy_compatibility_card_required",
              message: "A legacy compatibility mapping must retain a valid compatibility card.",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(updateMappingCompatibilityCard(19, null)).rejects.toThrow(
      "A legacy compatibility mapping must retain a valid compatibility card.",
    );
  });
});
