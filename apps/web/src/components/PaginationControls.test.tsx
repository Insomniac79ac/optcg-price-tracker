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
});
