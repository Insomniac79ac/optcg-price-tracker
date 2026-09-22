import { describe, expect, it } from "vitest";
import { maskReviewer } from "./maskReviewer";

describe("reviewer display privacy", () => {
  it.each([
    ["reviewer@example.com", "r***@example.com"],
    ["i@gmail.com", "i***@gmail.com"],
    ["malformed", "Reviewer recorded"],
    ["x@y@z.example", "Reviewer recorded"],
    [null, "Not returned"],
    [undefined, "Not returned"],
  ])("masks %s", (input, expected) => {
    expect(maskReviewer(input)).toBe(expected);
    if (input) expect(maskReviewer(input)).not.toBe(input);
  });
});
