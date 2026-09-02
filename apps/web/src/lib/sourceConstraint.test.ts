import { describe, expect, it } from "vitest";

import { describeSourceConstraint } from "./sourceConstraint";

describe("describeSourceConstraint", () => {
  it("turns platform_floor into collector-facing copy, never the enum name", () => {
    const copy = describeSourceConstraint("platform_floor");

    expect(copy?.label).toBe("Minimum listing price");
    expect(copy?.explanation).toBe(
      "This value is at the source's minimum listing price and may not reflect the card's actual market price.",
    );
    // Generic by design: no source is named and no threshold is quoted, so
    // this sentence cannot go stale when the backend's rule changes and is
    // already correct for any future source that gains a minimum.
    expect(copy?.explanation).not.toMatch(/snkrdunk/i);
    expect(copy?.explanation).not.toMatch(/[0-9]/);
    expect(copy?.tone).toBe("informational");
    expect(JSON.stringify(copy)).not.toContain("platform_floor");
  });

  it("turns below_platform_minimum into a mild-caution anomaly note", () => {
    const copy = describeSourceConstraint("below_platform_minimum");

    expect(copy?.label).toBe("Source data anomaly");
    expect(copy?.explanation).toBe(
      "This price is below the source's known minimum and is not used in Market Index.",
    );
    expect(copy?.explanation).not.toMatch(/snkrdunk/i);
    expect(copy?.explanation).not.toMatch(/[0-9]/);
    expect(copy?.tone).toBe("caution");
    // Its own sentence already says it, so callers must not add the generic line.
    expect(copy?.statesExclusion).toBe(true);
    expect(JSON.stringify(copy)).not.toContain("below_platform_minimum");
  });

  it("describes a sale price as informational and NOT excluded", () => {
    // The one constraint that does not mean "excluded". A sale price is a
    // real, current, buyable number that counts toward Market Index exactly
    // like any other retail price, so it must not borrow the amber caution
    // tone, and statesExclusion must stay false - SourceConstraintNote reads
    // it together with `eligible` to decide whether to add "Not used in
    // Market Index", and for a sale price it must not.
    const copy = describeSourceConstraint("sale_price");
    expect(copy?.label).toBe("Sale price");
    expect(copy?.tone).toBe("informational");
    expect(copy?.statesExclusion).toBe(false);
    expect(copy?.explanation).toMatch(/on sale/i);
  });

  it("never shows a former, struck or was-price anywhere in the sale copy", () => {
    // Atlas does not store the struck former price, so no copy may imply it
    // has one to show - and no number may appear that a reader could mistake
    // for a price.
    const copy = describeSourceConstraint("sale_price")!;
    const text = `${copy.label} ${copy.explanation}`;
    expect(text).not.toMatch(/was |before|previously|struck|former|original|regular/i);
    expect(text).not.toMatch(/[0-9]/);
    expect(text).not.toMatch(/[¥￥]/);
    expect(text).not.toMatch(/%|discount|off\b/i);
  });

  it("says nothing about a sale for the other constraints", () => {
    for (const constraint of ["platform_floor", "below_platform_minimum"]) {
      const copy = describeSourceConstraint(constraint)!;
      expect(`${copy.label} ${copy.explanation}`).not.toMatch(/sale/i);
    }
  });

  it("says nothing for an unconstrained value", () => {
    expect(describeSourceConstraint(null)).toBeNull();
    expect(describeSourceConstraint(undefined)).toBeNull();
    expect(describeSourceConstraint("")).toBeNull();
  });

  it("says nothing for a constraint this build has never heard of", () => {
    // A future backend release may add one. Showing its raw name would leak
    // internal vocabulary; inventing a label would state something we do not
    // know. Both are worse than staying quiet.
    expect(describeSourceConstraint("future_constraint")).toBeNull();
    expect(describeSourceConstraint("PLATFORM_FLOOR")).toBeNull();
  });

  it("cannot encode a price threshold, because it never sees a price", () => {
    // The strongest guarantee available: the function takes the backend's
    // verdict and nothing else - no value, no source name, no reference_type -
    // so a client-side rule like `source === "snkrdunk" && price === 1000`
    // cannot exist here even by accident.
    expect(describeSourceConstraint.length).toBe(1);
    // Same verdict in, same copy out - it has nothing else to vary on.
    expect(describeSourceConstraint("platform_floor")).toEqual(
      describeSourceConstraint("platform_floor"),
    );
    expect(describeSourceConstraint.toString()).not.toMatch(
      /value_jpy|reference_type|snkrdunk/i,
    );
  });

  it("states no source-specific fact anywhere in the mapping", () => {
    // The backend owns which platform has which minimum. Any source name or
    // number in this copy would be a second, silently-drifting copy of a rule
    // this app does not own.
    for (const constraint of [
      "platform_floor",
      "below_platform_minimum",
      "sale_price",
    ]) {
      const copy = describeSourceConstraint(constraint)!;
      const text = `${copy.label} ${copy.explanation}`;
      expect(text).not.toMatch(/snkrdunk|yuyutei|bandai/i);
      expect(text).not.toMatch(/[0-9]/);
      expect(text).not.toMatch(/[¥￥]/);
    }
  });
});
