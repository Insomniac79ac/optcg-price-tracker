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
    for (const constraint of ["platform_floor", "below_platform_minimum"]) {
      const copy = describeSourceConstraint(constraint)!;
      const text = `${copy.label} ${copy.explanation}`;
      expect(text).not.toMatch(/snkrdunk|yuyutei|bandai/i);
      expect(text).not.toMatch(/[0-9]/);
      expect(text).not.toMatch(/[¥￥]/);
    }
  });
});
