import { describe, expect, it } from "vitest";

import {
  isUnavailableSourceValue,
  SOURCE_PRICE_UNAVAILABLE_LABEL,
  unavailableSourceValues,
} from "./sourceAvailability";

function value(source: string, value_jpy: number | null) {
  return { source, value_jpy };
}

describe("unavailableSourceValues", () => {
  it("returns the sources that reported nothing when another one did", () => {
    const rows = unavailableSourceValues([
      value("yuyutei", 1980),
      value("snkrdunk", null),
    ]);
    expect(rows.map((r) => r.source)).toEqual(["snkrdunk"]);
  });

  it("does not care which source is the missing one", () => {
    const rows = unavailableSourceValues([
      value("yuyutei", null),
      value("snkrdunk", 1500),
    ]);
    expect(rows.map((r) => r.source)).toEqual(["yuyutei"]);
  });

  it("returns nothing when every source reported a price", () => {
    expect(
      unavailableSourceValues([value("yuyutei", 1980), value("snkrdunk", 1500)]),
    ).toEqual([]);
  });

  it("returns nothing when NO source reported a price", () => {
    // The precondition, and the reason this is a function rather than a
    // filter: with no price on screen there is no comparison to complete, and
    // "Index unavailable" already says the only thing there is to say.
    expect(
      unavailableSourceValues([value("yuyutei", null), value("snkrdunk", null)]),
    ).toEqual([]);
  });

  it("returns nothing for an empty source list", () => {
    expect(unavailableSourceValues([])).toEqual([]);
  });

  it("keeps the API's own order and names no source itself", () => {
    // A third source added server-side must appear without this module being
    // edited - it reads value_jpy and nothing else.
    const rows = unavailableSourceValues([
      value("cardrush", null),
      value("yuyutei", 1980),
      value("snkrdunk", null),
    ]);
    expect(rows.map((r) => r.source)).toEqual(["cardrush", "snkrdunk"]);
  });

  it("reads value_jpy alone - never eligibility, contribution or constraint", () => {
    // An ineligible platform-minimum price is still a price: it has a number,
    // so it is a priced row with its own constraint copy, never an absence.
    const rows = unavailableSourceValues([
      { ...value("snkrdunk", 120), eligible: false, constraint: "platform_floor" },
      { ...value("yuyutei", null), eligible: true, constraint: null },
    ]);
    expect(rows.map((r) => r.source)).toEqual(["yuyutei"]);
  });

  it("does not mutate or reorder the array it was given", () => {
    const sources = [value("yuyutei", 1980), value("snkrdunk", null)];
    const snapshot = JSON.parse(JSON.stringify(sources));
    unavailableSourceValues(sources);
    expect(sources).toEqual(snapshot);
  });
});

describe("isUnavailableSourceValue", () => {
  it("is true only for a null price", () => {
    expect(isUnavailableSourceValue(value("snkrdunk", null))).toBe(true);
    expect(isUnavailableSourceValue(value("snkrdunk", 1500))).toBe(false);
  });

  it("treats zero as a price, not an absence", () => {
    // ¥0 is not something this product renders, but if a backend ever sent
    // one it is a NUMBER and must not be laundered into "Price unavailable".
    expect(isUnavailableSourceValue(value("snkrdunk", 0))).toBe(false);
  });
});

describe("the wording", () => {
  it("is a sentence, not a number, a dash or an empty string", () => {
    expect(SOURCE_PRICE_UNAVAILABLE_LABEL).toBe("Price unavailable");
    expect(SOURCE_PRICE_UNAVAILABLE_LABEL).not.toMatch(/[0-9￥¥—–-]/);
  });
});
