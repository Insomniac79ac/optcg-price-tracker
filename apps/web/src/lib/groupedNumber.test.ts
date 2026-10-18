import { describe, expect, it } from "vitest";

import { applyEdit, caretAfterDigits, digitsBefore, displayFor, groupDigits, numberDigits, toAsciiDigits, withoutLeadingZeros } from "./groupedNumber";

describe("groupedNumber helpers", () => {
  it.each([
    ["", ""],
    ["7", "7"],
    ["999", "999"],
    ["1000", "1,000"],
    ["30000", "30,000"],
    ["100000000", "100,000,000"],
  ])("groups %j as %j", (digits, grouped) => expect(groupDigits(digits)).toBe(grouped));

  it("reads full-width digits as ASCII", () => {
    expect(toAsciiDigits("３０，０００円")).toBe("30，000円");
    expect(numberDigits("３０，０００")).toBe("30000");
  });

  it.each([
    ["¥30,000", "30000"],
    ["￥30,000", "30000"],
    ["30000円", "30000"],
    [" 30 000 ", "30000"],
    ["3、000", "3000"],
    ["", ""],
  ])("takes the digits of %j", (text, digits) => expect(numberDigits(text)).toBe(digits));

  it.each(["1,200.50", "-500", "1e3", "abc", "12a"])("leaves %j alone: not a whole number", (text) => expect(numberDigits(text)).toBeNull());

  it("drops leading zeros but keeps a lone zero", () => {
    expect(withoutLeadingZeros("007")).toBe("7");
    expect(withoutLeadingZeros("000")).toBe("0");
    expect(withoutLeadingZeros("0")).toBe("0");
  });

  it("maps carets by digits, not characters", () => {
    expect(digitsBefore("30,000", 3)).toBe(2);
    expect(digitsBefore("30,000", 4)).toBe(3);
    expect(caretAfterDigits("30,000", 2)).toBe(2);
    expect(caretAfterDigits("30,000", 3)).toBe(4);
    expect(caretAfterDigits("30,000", 0)).toBe(0);
    expect(caretAfterDigits("30,000", 99)).toBe(6);
  });

  it("shows stored digits grouped and anything else as typed", () => {
    expect(displayFor("30000")).toBe("30,000");
    expect(displayFor("")).toBe("");
    expect(displayFor("1,200.50")).toBe("1,200.50");
  });
});

describe("applyEdit", () => {
  it("groups as you type and keeps the caret at the end", () => {
    expect(applyEdit("3,000", "3,0000", 6, null)).toEqual({ value: "30000", display: "30,000", caret: 6 });
  });

  it("keeps the caret after the same digit when typing in the middle", () => {
    // 1,000 with the caret after the 1; type 5.
    expect(applyEdit("1,000", "15,000", 2, null)).toEqual({ value: "15000", display: "15,000", caret: 2 });
    // 12,345 with the caret before the 3; type 9 -> 129,345, caret after the 9.
    expect(applyEdit("12,345", "12,9345", 4, null)).toEqual({ value: "129345", display: "129,345", caret: 3 });
  });

  it("removes the digit before a comma on Backspace", () => {
    // 30,|000: the browser deleted the comma; the 0 before it goes instead.
    expect(applyEdit("30,000", "30000", 2, "backward")).toEqual({ value: "3000", display: "3,000", caret: 1 });
  });

  it("removes the digit after a comma on Delete", () => {
    // 30|,000: Delete took the comma; the 0 after it goes instead, and the
    // caret stays after the same two digits (3,0|00).
    expect(applyEdit("30,000", "30000", 2, "forward")).toEqual({ value: "3000", display: "3,000", caret: 3 });
  });

  it("deletes ordinary digits normally and regroups", () => {
    expect(applyEdit("30,000", "3,000", 1, "backward")).toEqual({ value: "3000", display: "3,000", caret: 1 });
    expect(applyEdit("1,234", "1,34", 2, "forward")).toEqual({ value: "134", display: "134", caret: 1 });
  });

  it("does not take an extra digit when a selection was deleted", () => {
    expect(applyEdit("30,000", "30000", 2, null)).toEqual({ value: "30000", display: "30,000", caret: 2 });
  });

  it("reads pastes with ¥, 円 and full-width digits", () => {
    expect(applyEdit("", "¥30,000", 7, null)).toEqual({ value: "30000", display: "30,000", caret: 6 });
    expect(applyEdit("", "30000円", 6, null)).toEqual({ value: "30000", display: "30,000", caret: 6 });
    expect(applyEdit("", "３００００", 5, null)).toEqual({ value: "30000", display: "30,000", caret: 6 });
  });

  it("leaves text that is not a whole number as typed", () => {
    expect(applyEdit("", "1,200.50", 8, null)).toEqual({ value: "1,200.50", display: "1,200.50", caret: 8 });
  });

  it("collapses leading zeros without losing the caret", () => {
    expect(applyEdit("0", "05", 2, null)).toEqual({ value: "5", display: "5", caret: 1 });
    expect(applyEdit("", "0", 1, null)).toEqual({ value: "0", display: "0", caret: 1 });
  });

  it("empties to an empty value", () => {
    expect(applyEdit("5", "", 0, "backward")).toEqual({ value: "", display: "", caret: 0 });
  });
});
