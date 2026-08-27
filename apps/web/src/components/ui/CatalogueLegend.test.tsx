import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CatalogueLegend } from "./CatalogueLegend";

/** The legend is the accessible route to the terminology - the one that has to
 * work without a mouse. These tests are about that, not about the copy (which
 * lib/terminology.test.ts owns). */
describe("catalogue legend", () => {
  it("is a real button, closed to begin with", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });

    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Nothing for assistive technology to walk past while it is closed.
    expect(screen.queryByRole("group", { name: "Catalogue terminology" })).toBeNull();
  });

  it("opens on click, and hovering alone does nothing", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });

    // Hover is not the mechanism - a phone has none.
    fireEvent.mouseOver(toggle);
    fireEvent.mouseEnter(toggle);
    expect(screen.queryByRole("group", { name: "Catalogue terminology" })).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();
  });

  it("is reachable and operable from the keyboard", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });

    toggle.focus();
    expect(toggle).toHaveFocus();
    // A native <button> activates on Enter/Space, which the browser turns into
    // a click - so asserting the click path is asserting the keyboard path.
    fireEvent.click(toggle);

    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();
  });

  it("opens on a tap, which is the mobile route", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });

    fireEvent.pointerDown(toggle);
    fireEvent.click(toggle);

    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();
  });

  it("closes on Escape and gives focus back to the toggle", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("group", { name: "Catalogue terminology" })).toBeNull();
    // A keyboard user is never dropped at the top of the document.
    expect(toggle).toHaveFocus();
  });

  it("closes when the pointer goes down outside it", () => {
    render(
      <div>
        <CatalogueLegend />
        <button type="button">elsewhere</button>
      </div>,
    );
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();

    fireEvent.pointerDown(screen.getByRole("button", { name: "elsewhere" }));

    expect(screen.queryByRole("group", { name: "Catalogue terminology" })).toBeNull();
  });

  it("stays open when the pointer goes down inside it", () => {
    render(<CatalogueLegend />);
    const toggle = screen.getByRole("button", { name: /what do these labels mean/i });
    fireEvent.click(toggle);
    const panel = screen.getByRole("group", { name: "Catalogue terminology" });

    fireEvent.pointerDown(panel);

    expect(screen.getByRole("group", { name: "Catalogue terminology" })).toBeTruthy();
  });

  it("explains every badge a collector meets on a tile", () => {
    render(<CatalogueLegend />);
    fireEvent.click(screen.getByRole("button", { name: /what do these labels mean/i }));

    for (const term of [
      "Alt Art",
      "Reprint",
      "SP Card",
      "Treasure Rare",
      "TR",
      "Set",
      "Found in",
      "Market Index",
      "Source range",
    ]) {
      expect(screen.getByText(term), `legend is missing ${term}`).toBeTruthy();
    }
    expect(screen.getByText("Another official artwork of the same card.")).toBeTruthy();
    expect(screen.getByText("A printing released again in another product.")).toBeTruthy();
  });

  it("groups the terms under the dimension each one belongs to", () => {
    render(<CatalogueLegend />);
    fireEvent.click(screen.getByRole("button", { name: /what do these labels mean/i }));

    // Real headings, so a screen reader can navigate by them and a sighted
    // reader can see which question each group answers.
    for (const heading of ["Rarity", "Special print", "Printing"]) {
      expect(
        screen.getByRole("heading", { name: heading }),
        `no heading for ${heading}`,
      ).toBeTruthy();
    }
  });

  it("says up front that rarity, special print and printing can all be true at once", () => {
    render(<CatalogueLegend />);
    fireEvent.click(screen.getByRole("button", { name: /what do these labels mean/i }));

    // Without this the tile reads as self-contradictory: Super Rare AND SP
    // Card AND Alt Art on one card.
    const intro = screen.getByText(/three different things/i);
    expect(intro.textContent).toContain("Super Rare");
    expect(intro.textContent).toContain("SP Card");
    expect(intro.textContent).toContain("Alt Art");
  });

  it("never presents SP Card or Treasure Rare as a rarity", () => {
    render(<CatalogueLegend />);
    fireEvent.click(screen.getByRole("button", { name: /what do these labels mean/i }));

    const panel = screen.getByRole("group", { name: "Catalogue terminology" });
    const sections = panel.querySelectorAll("section");
    const rarity = Array.from(sections).find(
      (section) => section.querySelector("h3")?.textContent === "Rarity",
    );

    expect(rarity, "no Rarity section").toBeTruthy();
    expect(rarity!.textContent).not.toContain("SP Card");
    expect(rarity!.textContent).not.toContain("Treasure Rare");
  });
});
