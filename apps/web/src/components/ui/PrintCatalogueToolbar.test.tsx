import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EMPTY_PRINT_FILTERS, type PrintCatalogueFilters } from "@/lib/catalogueState";
import { releaseFixture } from "@/lib/publicDiscoveryFixtures";
import { PrintCatalogueToolbar } from "./PrintCatalogueToolbar";

const changed = vi.fn();
const matchMedia = window.matchMedia;
const initial = { ...EMPTY_PRINT_FILTERS, releaseProductId: 186, legacySet: "OP-17", rarities: ["SR"], treatments: ["parallel"], q: "Luffy" };
function Toolbar({ filters = initial }: { filters?: PrintCatalogueFilters }) {
  const [value, setValue] = useState(filters);
  return <PrintCatalogueToolbar releases={releaseFixture.items} facets={{ rarities: ["SR", "R"], treatments: ["normal", "parallel"], languages: ["jp"], verification_statuses: [] }} filters={value}
    onChange={(next) => { changed(next); setValue(next); }} />;
}
const openRelease = () => fireEvent.click(screen.getByRole("button", { name: /^Release / }));
beforeEach(() => {
  changed.mockReset();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});
afterEach(() => { window.matchMedia = matchMedia; });

describe("Release toolbar integration", () => {
  it("commits a replacement ID immediately, clears legacySet and preserves other filters", () => {
    render(<Toolbar />);
    openRelease();
    fireEvent.click(screen.getByRole("radio", { name: "OP-16 — THE TIME OF BATTLE" }));
    expect(changed).toHaveBeenCalledExactlyOnceWith({ ...initial, releaseProductId: 185, legacySet: "" });
  });

  it("clears only Release, including the legacy set", () => {
    render(<Toolbar />);
    openRelease();
    fireEvent.click(screen.getByRole("button", { name: "Clear release" }));
    expect(changed).toHaveBeenCalledExactlyOnceWith({ ...initial, releaseProductId: null, legacySet: "" });
  });

  describe("mobile draft", () => {
    beforeEach(() => {
      window.matchMedia = vi.fn().mockImplementation(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    });

    it("replaces the draft only, keeps the sheet open on Escape, and commits once on Apply", () => {
      render(<Toolbar />);
      fireEvent.click(screen.getByRole("button", { name: "Filters · 2" }));
      const sheet = screen.getByRole("dialog", { name: "Filters" });
      openRelease();
      fireEvent.click(screen.getByRole("radio", { name: "OP-16 — THE TIME OF BATTLE" }));
      expect(changed).not.toHaveBeenCalled();
      fireEvent.keyDown(document.activeElement!, { key: "Escape" });
      expect(sheet).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Release OP-16" })).toHaveFocus();
      fireEvent.click(within(sheet).getByRole("button", { name: "Apply filters" }));
      expect(changed).toHaveBeenCalledExactlyOnceWith({ ...initial, releaseProductId: 185, legacySet: "" });
    });

    it("discards a release draft on cancel and restores the committed release on reopen", () => {
      render(<Toolbar />);
      fireEvent.click(screen.getByRole("button", { name: "Filters · 2" }));
      openRelease();
      fireEvent.click(screen.getByRole("button", { name: "Clear release" }));
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      fireEvent.click(screen.getByRole("button", { name: "Close filters" }));
      expect(changed).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Filters · 2" }));
      expect(screen.getByRole("button", { name: "Release OP-17" })).toBeInTheDocument();
    });

    it("clears the entire draft only when Apply is pressed", () => {
      render(<Toolbar />);
      fireEvent.click(screen.getByRole("button", { name: "Filters · 2" }));
      fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
      expect(changed).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Release All releases" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Rarity Any" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Treatment Any" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
      expect(changed).toHaveBeenCalledExactlyOnceWith(EMPTY_PRINT_FILTERS);
    });
  });
});
