"use client";

import { useLayoutEffect, useRef, useState, type ChangeEvent, type InputHTMLAttributes } from "react";

import { applyEdit, displayFor } from "@/lib/groupedNumber";

type Passthrough = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange" | "type" | "inputMode" | "pattern">;

/** A whole-number field (yen, quantities) that shows thousands commas as the
 * collector types: 30000 reads 30,000. `value` and `onValueChange` carry
 * plain digits, so what the form validates and sends never contains a comma;
 * text that is not a whole number (1,200.50, letters) is passed on as typed
 * for the form's own message.
 *
 * The caret stays after the same digit it was after, Backspace or Delete on
 * a comma removes the digit beside it, pastes with ¥ or 円 and full-width
 * digits are read as numbers, and a Japanese IME is left alone until the
 * composition ends. inputMode="numeric" opens the number pad on phones; no
 * `pattern`, which commas would fail. */
export function GroupedNumberInput({
  value,
  onValueChange,
  ...rest
}: Passthrough & { value: string; onValueChange: (value: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const collapsed = useRef(true);
  const [composing, setComposing] = useState<string | null>(null);
  const display = composing ?? displayFor(value);

  useLayoutEffect(() => {
    const input = ref.current;
    if (caret.current === null || !input) return;
    if (input.ownerDocument.activeElement === input) input.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  });

  function remember(input: HTMLInputElement) {
    collapsed.current = input.selectionStart === input.selectionEnd;
  }

  function commit(input: HTMLInputElement, inputType: string | undefined) {
    const deletion = !collapsed.current
      ? null
      : inputType === "deleteContentForward"
        ? "forward"
        : inputType === "deleteContentBackward" || inputType === undefined
          ? "backward"
          : null;
    const edit = applyEdit(display, input.value, input.selectionStart ?? input.value.length, deletion);
    caret.current = edit.caret;
    collapsed.current = true;
    // Shown at once, even when the stored value is unchanged (a comma put back).
    input.value = edit.display;
    input.setSelectionRange(edit.caret, edit.caret);
    onValueChange(edit.value);
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const native = event.nativeEvent as InputEvent;
    if (composing !== null || native.isComposing) {
      setComposing(event.target.value);
      return;
    }
    commit(event.target, native.inputType);
  }

  return (
    <input
      {...rest}
      ref={ref}
      type="text"
      inputMode="numeric"
      autoComplete="off"
      value={display}
      onChange={handleChange}
      onKeyDown={(event) => {
        remember(event.currentTarget);
        rest.onKeyDown?.(event);
      }}
      onSelect={(event) => {
        remember(event.currentTarget);
        rest.onSelect?.(event);
      }}
      onCompositionStart={(event) => {
        setComposing(event.currentTarget.value);
        rest.onCompositionStart?.(event);
      }}
      onCompositionEnd={(event) => {
        const input = event.currentTarget;
        setComposing(null);
        commit(input, "insertCompositionText");
        rest.onCompositionEnd?.(event);
      }}
    />
  );
}
