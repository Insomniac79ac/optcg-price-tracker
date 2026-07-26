import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KeyboardShortcutsModal } from "./KeyboardShortcutsModal";

describe("KeyboardShortcutsModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<KeyboardShortcutsModal open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists the goto sequences and general shortcuts when open", () => {
    render(<KeyboardShortcutsModal open onClose={vi.fn()} />);
    expect(screen.getByText("Keyboard shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Go to My Collection")).toBeInTheDocument();
    expect(screen.getByText("g c")).toBeInTheDocument();
    expect(screen.getByText("Open the command palette")).toBeInTheDocument();
  });

  it("calls onClose when Close is clicked", () => {
    const onClose = vi.fn();
    render(<KeyboardShortcutsModal open onClose={onClose} />);
    fireEvent.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalled();
  });
});
