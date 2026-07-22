import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QuickActionBar } from "./QuickActionBar";

describe("QuickActionBar", () => {
  it("renders nothing when there are no actions", () => {
    const { container } = render(<QuickActionBar actions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a link for href actions", () => {
    render(<QuickActionBar actions={[{ label: "Go to Wishlist", href: "/wishlist" }]} />);
    const link = screen.getByText("Go to Wishlist");
    expect(link.closest("a")).toHaveAttribute("href", "/wishlist");
  });

  it("calls onClick for button actions", () => {
    const onClick = vi.fn();
    render(<QuickActionBar actions={[{ label: "Run recheck", onClick }]} />);
    fireEvent.click(screen.getByText("Run recheck"));
    expect(onClick).toHaveBeenCalled();
  });
});
