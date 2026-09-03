import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoTip } from "./InfoTip";

/** The explainer beside an evidence-type label.
 *
 * Every assertion here exists because a hover tooltip would have failed it.
 * Atlas is browsed on phones, where there is no hover at all, and a collector
 * navigating by keyboard has no pointer to hover with - so "can this be opened
 * without a mouse, and closed again without trapping me" is the whole test
 * file, not an accessibility footnote appended to it.
 */

const TEXT =
  "Lowest current listing observed on this source. Asking prices are not completed sales.";

function renderTip() {
  return render(<InfoTip label="About Current listing" text={TEXT} />);
}

function trigger() {
  return screen.getByRole("button", { name: "About Current listing" });
}

describe("InfoTip", () => {
  it("starts closed, saying so where assistive technology can read it", () => {
    renderTip();

    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(TEXT)).toBeNull();
  });

  it("opens on tap - the interaction a phone actually has", () => {
    renderTip();

    fireEvent.click(trigger());

    expect(screen.getByText(TEXT)).toBeTruthy();
  });

  it("is a real button, so Enter and Space open it with no code of our own", () => {
    // This is the assertion that rules out every hover-only and div-based
    // affordance. A native <button> that is focusable and not disabled is
    // activated by Enter and by Space by the platform itself - behaviour a
    // handmade keydown handler on a <span> would have to reimplement and would
    // get subtly wrong. So the test pins the element, not a synthetic event.
    renderTip();

    const button = trigger();
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("type")).toBe("button");
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(button.getAttribute("tabindex")).toBeNull();

    button.focus();
    expect(document.activeElement).toBe(button);
  });

  it("ties the panel to the trigger so a screen reader can follow it", () => {
    renderTip();

    const button = trigger();
    fireEvent.click(button);

    expect(button.getAttribute("aria-expanded")).toBe("true");
    // aria-controls must point at the panel that actually exists, not at a
    // hopeful id: an announced relationship to nothing is worse than none.
    const panelId = button.getAttribute("aria-controls")!;
    expect(document.getElementById(panelId)?.textContent).toBe(TEXT);
  });

  it("closes on Escape and hands focus back to the trigger", () => {
    renderTip();

    const button = trigger();
    fireEvent.click(button);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByText(TEXT)).toBeNull();
    // Without this a keyboard user closing the panel is dropped at the top of
    // the document and has to Tab back through the whole page.
    expect(document.activeElement).toBe(button);
  });

  it("closes when the reader taps somewhere else", () => {
    render(
      <div>
        <InfoTip label="About Current listing" text={TEXT} />
        <p data-testid="elsewhere">the rest of the page</p>
      </div>,
    );

    fireEvent.click(trigger());
    expect(screen.getByText(TEXT)).toBeTruthy();

    fireEvent.mouseDown(screen.getByTestId("elsewhere"));
    expect(screen.queryByText(TEXT)).toBeNull();
  });

  it("stays open when the reader taps inside the panel itself", () => {
    renderTip();

    fireEvent.click(trigger());
    fireEvent.mouseDown(screen.getByText(TEXT));

    expect(screen.getByText(TEXT)).toBeTruthy();
  });

  it("toggles shut when the trigger is pressed a second time", () => {
    renderTip();

    const button = trigger();
    fireEvent.click(button);
    fireEvent.click(button);

    expect(screen.queryByText(TEXT)).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("gives two tips on one page their own panel ids", () => {
    render(
      <div>
        <InfoTip label="About Retail price" text="one" />
        <InfoTip label="About Current listing" text="two" />
      </div>,
    );

    const first = screen.getByRole("button", { name: "About Retail price" });
    const second = screen.getByRole("button", { name: "About Current listing" });
    expect(first.getAttribute("aria-controls")).not.toBe(
      second.getAttribute("aria-controls"),
    );

    // ...and opening one leaves the other alone.
    fireEvent.click(second);
    expect(screen.getByText("two")).toBeTruthy();
    expect(screen.queryByText("one")).toBeNull();
  });

  it("is a plain disclosure, not a modal - the page behind it stays reachable", () => {
    render(
      <div>
        <InfoTip label="About Current listing" text={TEXT} />
        <button type="button">Add to collection</button>
      </div>,
    );

    fireEvent.click(trigger());

    // No focus trap, no inert background, no overlay: it explains a word
    // beside a price and must not take over the page to do it.
    expect(screen.getByRole("button", { name: "Add to collection" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("removes its listeners when it closes, leaving nothing bound to the document", () => {
    renderTip();

    fireEvent.click(trigger());
    fireEvent.keyDown(document, { key: "Escape" });
    // A stale mousedown listener from a closed tip would swallow nothing
    // visibly but would run on every click on the page for the rest of the
    // session. Reopening and closing again must be idempotent.
    fireEvent.click(trigger());
    expect(screen.getByText(TEXT)).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText(TEXT)).toBeNull();
  });
});
