/** Pure helpers behind GroupedNumberInput: whole numbers shown with thousands
 * commas while typing (30000 reads 30,000), stored and sent as plain digits.
 *
 * Accepted as part of a number: ASCII and full-width digits, commas
 * (ASCII and full-width), the ideographic comma, spaces, ¥ / ￥ and 円, so
 * "¥30,000", "３０，０００" and "30000円" all read as 30000. Anything else (a
 * decimal point, a minus sign, letters) is not a whole number of yen or cards,
 * and the text is left as typed for the form to refuse. */

const FULL_WIDTH_DIGIT = /[０-９]/g;
const IGNORED = /[,，、\s¥￥円]/g;

/** Full-width digits (０-９) to ASCII; every other character unchanged. */
export function toAsciiDigits(text: string): string {
  return text.replace(FULL_WIDTH_DIGIT, (digit) => String.fromCharCode(digit.charCodeAt(0) - 0xfee0));
}

function isDigit(char: string): boolean {
  return char >= "0" && char <= "9";
}

/** The plain digits of `text`, or null when it holds anything that is not
 * part of a whole number. "" for text with no digits at all. */
export function numberDigits(text: string): string | null {
  const stripped = toAsciiDigits(text).replace(IGNORED, "");
  return /^\d*$/.test(stripped) ? stripped : null;
}

/** "007" reads as 7; a lone 0 stays (¥0 paid is a real answer). */
export function withoutLeadingZeros(digits: string): string {
  return digits.replace(/^0+(?=\d)/, "");
}

/** "30000" to "30,000". Digits only in, so nothing is ever reinterpreted. */
export function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** How many digits sit before `position` in `text`. */
export function digitsBefore(text: string, position: number): number {
  let count = 0;
  for (const char of toAsciiDigits(text.slice(0, position))) if (isDigit(char)) count += 1;
  return count;
}

/** The caret position in grouped `formatted` text that sits right after its
 * `count`-th digit (0 is the start). */
export function caretAfterDigits(formatted: string, count: number): number {
  if (count <= 0) return 0;
  let seen = 0;
  for (let index = 0; index < formatted.length; index += 1) {
    if (isDigit(formatted[index])) {
      seen += 1;
      if (seen === count) return index + 1;
    }
  }
  return formatted.length;
}

export interface Edit {
  /** What the form stores: plain digits, or the text as typed when it is not
   * a whole number. */
  value: string;
  /** What the field shows. */
  display: string;
  /** Where the caret goes in `display`. */
  caret: number;
}

/** One edit of the field: `next` is its text after the browser applied the
 * keystroke, paste or cut, `caret` the browser's caret in it, `previous` the
 * text shown before. `deletion` says which way a delete key went, and is only
 * set when nothing was selected, so a lone comma removed by Backspace or
 * Delete takes the digit beside it instead of being put straight back. */
export function applyEdit(
  previous: string,
  next: string,
  caret: number,
  deletion: "backward" | "forward" | null,
): Edit {
  const parsed = numberDigits(next);
  if (parsed === null) return { value: next, display: next, caret };

  let digits = parsed;
  let before = digitsBefore(next, caret);
  if (deletion && next.length < previous.length && digits === numberDigits(previous)) {
    const at = deletion === "backward" ? before - 1 : before;
    if (at >= 0 && at < digits.length) {
      digits = digits.slice(0, at) + digits.slice(at + 1);
      before = at;
    }
  }

  const trimmed = withoutLeadingZeros(digits);
  before = Math.max(0, before - (digits.length - trimmed.length));
  const display = groupDigits(trimmed);
  return { value: trimmed, display, caret: caretAfterDigits(display, before) };
}

/** What the field shows for a stored value: grouped when it is plain digits,
 * as typed otherwise. */
export function displayFor(value: string): string {
  return /^\d+$/.test(value) ? groupDigits(value) : value;
}
