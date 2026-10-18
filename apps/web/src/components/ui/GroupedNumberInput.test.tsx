import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { GroupedNumberInput } from "./GroupedNumberInput";

function Field({ initial = "", onValue }: { initial?: string; onValue?: (value: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="n">Amount</label>
      <GroupedNumberInput
        id="n"
        value={value}
        onValueChange={(next) => {
          setValue(next);
          onValue?.(next);
        }}
      />
      <output data-testid="stored">{value}</output>
    </>
  );
}

function field() {
  return screen.getByLabelText("Amount") as HTMLInputElement;
}

/** The browser's own edit: new text and caret, then the input event. */
function edit(input: HTMLInputElement, text: string, caret: number, inputType?: string) {
  input.focus();
  fireEvent.input(input, { target: { value: text, selectionStart: caret, selectionEnd: caret }, inputType });
}

/** A key press with a collapsed caret at `at`, as the browser sees it first. */
function keyAt(input: HTMLInputElement, key: string, at: number) {
  input.focus();
  input.setSelectionRange(at, at);
  fireEvent.keyDown(input, { key });
}

describe("GroupedNumberInput", () => {
  it("is a text field with the numeric keyboard and no pattern", () => {
    render(<Field />);
    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveAttribute("inputmode", "numeric");
    expect(field()).not.toHaveAttribute("pattern");
    expect(field()).toHaveAttribute("autocomplete", "off");
  });

  it("shows a stored number with commas", () => {
    render(<Field initial="30000" />);
    expect(field().value).toBe("30,000");
  });

  it("adds commas while typing and stores plain digits", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    for (const text of ["3", "30", "300", "3000", "3,0000"]) edit(field(), text, text.length, "insertText");
    expect(field().value).toBe("30,000");
    expect(screen.getByTestId("stored")).toHaveTextContent(/^30000$/);
    expect(onValue).toHaveBeenLastCalledWith("30000");
    expect(field().selectionStart).toBe(6);
  });

  it("keeps the caret after the digit just typed in the middle", () => {
    render(<Field initial="12345" />);
    // 12,|345 -> type 9
    edit(field(), "12,9345", 4, "insertText");
    expect(field().value).toBe("129,345");
    expect(field().selectionStart).toBe(3);
  });

  it("Backspace on a comma removes the digit before it", () => {
    render(<Field initial="30000" />);
    keyAt(field(), "Backspace", 3);
    edit(field(), "30000", 2, "deleteContentBackward");
    expect(field().value).toBe("3,000");
    expect(screen.getByTestId("stored")).toHaveTextContent(/^3000$/);
    expect(field().selectionStart).toBe(1);
  });

  it("Delete on a comma removes the digit after it", () => {
    render(<Field initial="30000" />);
    keyAt(field(), "Delete", 2);
    edit(field(), "30000", 2, "deleteContentForward");
    expect(field().value).toBe("3,000");
    expect(screen.getByTestId("stored")).toHaveTextContent(/^3000$/);
    // Still after the same two digits: 3,0|00.
    expect(field().selectionStart).toBe(3);
  });

  it.each([
    ["¥30,000", "30000"],
    ["30000円", "30000"],
    ["￥30,000", "30000"],
    ["３００００", "30000"],
    ["３０，０００", "30000"],
  ])("reads a paste of %j as %j", (pasted, digits) => {
    render(<Field />);
    edit(field(), pasted, pasted.length, "insertFromPaste");
    expect(field().value).toBe("30,000");
    expect(screen.getByTestId("stored").textContent).toBe(digits);
  });

  it("passes text that is not a whole number on as typed", () => {
    render(<Field />);
    edit(field(), "1,200.50", 8, "insertFromPaste");
    expect(field().value).toBe("1,200.50");
    expect(screen.getByTestId("stored")).toHaveTextContent("1,200.50");
  });

  it("leaves a Japanese IME composition alone until it ends", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    const input = field();
    input.focus();
    fireEvent.compositionStart(input);
    fireEvent.input(input, { target: { value: "３００００" }, isComposing: true });
    expect(input.value).toBe("３００００");
    expect(onValue).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input, { target: { value: "３００００", selectionStart: 5, selectionEnd: 5 } });
    expect(input.value).toBe("30,000");
    expect(onValue).toHaveBeenLastCalledWith("30000");
  });
});
