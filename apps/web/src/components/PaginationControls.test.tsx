import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PaginationControls } from "./PaginationControls";

describe("PaginationControls", () => {
  it("renders the range text and enabled Next when there is a next page", () => {
    render(
      <PaginationControls offset={0} limit={100} total={350} onOffsetChange={() => {}} />,
    );
    expect(screen.getByText("1–100 of 350")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("disables Previous on the first page and Next on the last page", () => {
    render(
      <PaginationControls offset={300} limit={100} total={350} onOffsetChange={() => {}} />,
    );
    expect(screen.getByText("301–350 of 350")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
  });

  it("calls onOffsetChange with the next/previous offset", () => {
    const onOffsetChange = vi.fn();
    render(
      <PaginationControls offset={100} limit={100} total={350} onOffsetChange={onOffsetChange} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onOffsetChange).toHaveBeenCalledWith(200);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onOffsetChange).toHaveBeenCalledWith(0);
  });

  it("does not crash and shows a 0-results state for an empty list, with no controls", () => {
    render(<PaginationControls offset={0} limit={100} total={0} onOffsetChange={() => {}} />);
    expect(screen.getByText("0 results")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
  });

  it("hides Previous/Next/page-count when total <= limit (nothing to page through)", () => {
    render(<PaginationControls offset={0} limit={100} total={40} onOffsetChange={() => {}} />);
    expect(screen.getByText("1–40 of 40")).toBeInTheDocument();
    expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
  });

  it("renders the dense list-page layout by default - no landmark, no section border", () => {
    // The guard for every admin/internal call site: the default rendering must
    // be what it was before the catalogue variant existed, so adding a variant
    // to /cards cannot quietly restyle fifteen other pages.
    const { container } = render(
      <PaginationControls offset={0} limit={100} total={350} onOffsetChange={() => {}} />,
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(container.querySelector("nav")).toBeNull();
    expect(container.firstElementChild?.className).toContain("justify-between");
    expect(container.firstElementChild?.className).not.toContain("border-t");
    // Bare digits, no thousands separator, exactly as the admin tables show.
    expect(screen.getByText("1–100 of 350")).toBeInTheDocument();
  });
});

/** The public /cards presentation. Layout and emphasis only - every
 * assertion about *behaviour* below is that it matches the default. */
describe("PaginationControls (catalogue variant)", () => {
  const catalogue = (props: Partial<Parameters<typeof PaginationControls>[0]> = {}) =>
    render(
      <PaginationControls
        offset={0}
        limit={24}
        total={4281}
        onOffsetChange={() => {}}
        variant="catalogue"
        {...props}
      />,
    );

  it("is a labelled navigation landmark with a top separator, in normal flow", () => {
    const { container } = catalogue();
    const nav = screen.getByRole("navigation", { name: "Catalogue pagination" });
    expect(nav).toBeInTheDocument();
    expect(nav.className).toContain("border-t");
    // Not sticky, not floating - it scrolls with the grid it belongs to.
    expect(container.innerHTML).not.toMatch(/sticky|fixed/);
  });

  it("centres Previous / page status / Next as one group", () => {
    catalogue();
    const group = screen.getByRole("button", { name: "Previous" }).parentElement;
    // Centred as a group, and symmetric within it: equal side columns are what
    // put the page status on the same centre axis as the range line below,
    // despite "Previous" being the wider label.
    expect(group?.className).toContain("mx-auto");
    expect(group?.className).toContain("grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]");
    expect(group).toContainElement(screen.getByText("Page 1 of 179"));
    expect(group).toContainElement(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 1 of 179").className).toContain("text-center");
  });

  it("keeps the status column steady as the page number grows", () => {
    // Without a min-width the buttons would shift sideways between "Page 1 of
    // 179" and "Page 179 of 179" - a control that moves under the cursor
    // between clicks.
    catalogue();
    expect(screen.getByText("Page 1 of 179").className).toContain("min-w-[8.5rem]");
  });

  it("gives the page status primary weight above a secondary result range", () => {
    catalogue();
    const status = screen.getByText("Page 1 of 179");
    expect(status.className).toContain("text-base");
    expect(status.className).toContain("text-text-primary");

    const range = screen.getByText("Showing 1–24 of 4,281");
    expect(range.className).toContain("text-xs");
    expect(range.className).toContain("text-text-muted");
  });

  it("keeps Previous and Next to a 44px minimum touch target", () => {
    catalogue();
    for (const name of ["Previous", "Next"]) {
      const button = screen.getByRole("button", { name });
      // Tailwind's `11` scale step is 2.75rem = 44px.
      expect(button.className).toContain("min-h-11");
      expect(button.className).toContain("min-w-11");
    }
  });

  it("disables Previous on the first page", () => {
    catalogue();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
    expect(screen.getByText("Showing 1–24 of 4,281")).toBeInTheDocument();
  });

  it("enables both controls on a middle page", () => {
    catalogue({ offset: 2160 });
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
    expect(screen.getByText("Page 91 of 179")).toBeInTheDocument();
    expect(screen.getByText("Showing 2,161–2,184 of 4,281")).toBeInTheDocument();
  });

  it("disables Next on the last page and clamps the range to the total", () => {
    catalogue({ offset: 4272 });
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
    expect(screen.getByText("Page 179 of 179")).toBeInTheDocument();
    expect(screen.getByText("Showing 4,273–4,281 of 4,281")).toBeInTheDocument();
  });

  it("navigates by exactly one page, the same offsets as the default variant", () => {
    const onOffsetChange = vi.fn();
    catalogue({ offset: 24, onOffsetChange });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onOffsetChange).toHaveBeenCalledWith(48);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onOffsetChange).toHaveBeenCalledWith(0);
  });

  it("hides the controls but keeps the range when everything fits on one page", () => {
    catalogue({ total: 12 });
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1–12 of 12")).toBeInTheDocument();
  });

  it("does not crash on an empty list", () => {
    catalogue({ total: 0 });
    expect(screen.getByText("0 results")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });
});
