import { describe, expect, it } from "vitest";

import { invalidRouteIdResponse, isNumericRouteId } from "./routeId";

describe("isNumericRouteId (audit F8)", () => {
  it.each(["1", "42", "007", "1234567890"])("accepts %s", (id) => {
    expect(isNumericRouteId(id)).toBe(true);
  });

  it.each(["", "..", "1/../admin/cards", "1%2F..%2Fadmin", "../2", "1?x=1", "-1", "1.5", " 1", "1\n", "abc"])(
    "refuses %j",
    (id) => {
      expect(isNumericRouteId(id)).toBe(false);
    },
  );

  it("answers a refused id with a plain 404", async () => {
    const res = invalidRouteIdResponse();
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "Not found" });
  });
});
