import { readFileSync } from "node:fs";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => null }));
import { AlternativeCard } from "./AlternativeCard";
import { makeAlternative } from "../proposalReview.fixtures";

describe("printing evidence card", () => {
  it("keeps primary identity visible and technical metadata collapsed", () => {
    const { container } = render(<AlternativeCard alternative={makeAlternative()} />);
    const primary = container.querySelector('[data-print-metadata="primary"]')!;
    for (const label of ["Exact release", "Printing label", "Special print", "Official rarity", "Treatment", "Language", "Print state"]) {
      expect(within(primary as HTMLElement).getByText(label)).toBeVisible();
    }
    const technical = screen.getByText("Technical print metadata").closest("details")!;
    expect(technical.open).toBe(false);
    for (const label of ["Alternative ID", "CardPrint ID", "Official asset variant", "Artwork key", "Review disposition", "Reviewed at", "Alternative created", "Alternative updated"]) {
      expect(within(technical).getByText(label)).toBeInTheDocument();
    }
    for (const value of primary.querySelectorAll("dd")) {
      expect(value.className).toContain("break-words");
      expect(value.className).not.toMatch(/anywhere|break-all/);
    }
    expect(screen.getByText("Recommended proposal")).toBeVisible();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
  });
  it.each(["ja", "jp"])("displays Japanese for the persisted language code %s", (language) => {
    render(<AlternativeCard alternative={makeAlternative({ language })} />);
    expect(screen.getByText("Japanese")).toBeVisible();
  });
  it("keeps each evidence section explicit when empty and artwork uncropped", () => {
    render(<AlternativeCard alternative={makeAlternative({ supporting_evidence: [], missing_evidence: [], conflict_reasons: [] })} />);
    for (const title of ["Supporting evidence", "Missing evidence", "Conflict reasons"]) {
      expect(within(screen.getByRole("heading", { name: title }).closest("section")!).getByText("None recorded")).toBeVisible();
    }
    expect(screen.getByRole("img").className).toContain("object-contain");
  });
  it("uses one outer row and stacks the artwork before columns become cramped", () => {
    const css = readFileSync("src/app/admin/(protected)/source-mapping-proposals/[id]/AlternativeCard.module.css", "utf8");
    expect(css).toContain("container: printing / inline-size");
    expect(css).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(css).toContain("@container printing (min-width: 56rem)");
    expect(css).toContain("minmax(15rem, 20rem) minmax(0, 1fr)");
    expect(css).toContain("repeat(2, minmax(0, 1fr))");
    expect(css).not.toMatch(/repeat\(3|anywhere|break-all/);
    const page = readFileSync("src/app/admin/(protected)/source-mapping-proposals/[id]/page.tsx", "utf8");
    expect(page).toContain('className="grid min-w-0 grid-cols-1 gap-5" data-proposed-printings');
    expect(page).not.toContain('className="grid gap-4 lg:grid-cols-2"');
  });
});
