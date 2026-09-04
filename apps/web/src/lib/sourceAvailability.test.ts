import { describe, expect, it } from "vitest";

import {
  describeUnavailableSource,
  isUnavailableSourceValue,
  SOURCE_NO_LISTING_LABEL,
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

  it("keeps the two absences distinct so neither can stand in for the other", () => {
    expect(SOURCE_NO_LISTING_LABEL).toBe("No current listing");
    expect(SOURCE_NO_LISTING_LABEL).not.toMatch(/[0-9￥¥—–]/);
    expect(SOURCE_NO_LISTING_LABEL).not.toBe(SOURCE_PRICE_UNAVAILABLE_LABEL);
  });
});

function absent(source: string, ineligible_reason: string | null) {
  return { source, value_jpy: null, ineligible_reason };
}

describe("describeUnavailableSource", () => {
  it("says 'No current listing' for SNKRDUNK's insufficient_sold_and_no_floor", () => {
    const copy = describeUnavailableSource(
      absent("snkrdunk", "insufficient_sold_and_no_floor"),
    );
    expect(copy.label).toBe("No current listing");
    expect(copy.explanation).toBe(
      "No active listing was observed on SNKRDUNK. This does not necessarily " +
        "mean the card has low value; there may simply be no seller listing it " +
        "individually right now.",
    );
  });

  it("does not claim the card is cheap, and says so explicitly", () => {
    // The whole reason the disclosure exists: an absent listing is not a
    // verdict on value, and the sentence has to be the one that says so.
    const copy = describeUnavailableSource(
      absent("snkrdunk", "insufficient_sold_and_no_floor"),
    );
    expect(copy.explanation).toMatch(/does not necessarily mean the card has low value/);
    expect(copy.explanation).not.toMatch(/[0-9￥¥]/);
  });

  it("keeps the generic wording for every other null-price state", () => {
    // no_observation is the collector-has-not-reached-it case: we do not know
    // that nobody is selling, only that we have not looked successfully.
    expect(describeUnavailableSource(absent("snkrdunk", "no_observation")).label).toBe(
      "Price unavailable",
    );
    expect(describeUnavailableSource(absent("yuyutei", "no_observation")).label).toBe(
      "Price unavailable",
    );
    expect(describeUnavailableSource(absent("yuyutei", null)).label).toBe(
      "Price unavailable",
    );
    expect(
      describeUnavailableSource({ source: "yuyutei", value_jpy: null }).label,
    ).toBe("Price unavailable");
  });

  it("carries no disclosure where there is nothing extra to explain", () => {
    expect(describeUnavailableSource(absent("snkrdunk", "no_observation")).explanation)
      .toBeNull();
    expect(describeUnavailableSource(absent("yuyutei", null)).explanation).toBeNull();
  });

  it("keys on the reason, never on the source name plus a null price", () => {
    // This is the guard the whole module is shaped around. A SNKRDUNK row with
    // no number is NOT enough - only the backend's own verdict is.
    expect(describeUnavailableSource(absent("snkrdunk", null)).label).toBe(
      "Price unavailable",
    );
    expect(describeUnavailableSource(absent("snkrdunk", "stale")).label).toBe(
      "Price unavailable",
    );
  });

  it("will not print a sentence about SNKRDUNK under another source", () => {
    // The reason identifies the state; the source check keeps copy that NAMES
    // SNKRDUNK from appearing under a future source reporting the same reason.
    const copy = describeUnavailableSource(
      absent("cardrush", "insufficient_sold_and_no_floor"),
    );
    expect(copy.label).toBe("Price unavailable");
    expect(copy.explanation).toBeNull();
  });

  it("falls back to the generic wording for a reason this build has never heard of", () => {
    expect(
      describeUnavailableSource(absent("snkrdunk", "some_future_backend_reason")).label,
    ).toBe("Price unavailable");
  });

  it("never applies the specific wording to a row that has a number", () => {
    // A ¥1,000 platform-floor listing is a PRICE with a constraint. It is never
    // routed through here, and if it were it must not be laundered into an
    // absence - so this fails closed rather than trusting the caller.
    const priced = {
      source: "snkrdunk",
      value_jpy: 1000,
      ineligible_reason: "platform_floor",
    };
    expect(describeUnavailableSource(priced).label).toBe("Price unavailable");
    expect(describeUnavailableSource(priced).explanation).toBeNull();
  });
});
