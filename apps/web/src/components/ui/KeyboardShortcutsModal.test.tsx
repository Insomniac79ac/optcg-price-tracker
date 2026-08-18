import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useSession } = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("next-auth/react", () => ({ useSession }));

import { KeyboardShortcutsModal } from "./KeyboardShortcutsModal";

describe("KeyboardShortcutsModal", () => {
  beforeEach(() => {
    useSession.mockReturnValue({ data: { user: {} }, status: "authenticated" });
  });

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

  it("hides the collector-only goto sequences from a signed-out visitor", () => {
    useSession.mockReturnValue({ data: null, status: "unauthenticated" });
    render(<KeyboardShortcutsModal open onClose={vi.fn()} />);
    // Every goto target is a collector-tier route behind the sign-in wall,
    // so documenting them to a signed-out reader promises nothing usable.
    expect(screen.queryByText("Go to My Collection")).not.toBeInTheDocument();
    expect(screen.queryByText("g c")).not.toBeInTheDocument();
    // The general shortcuts all work signed-out and stay.
    expect(screen.getByText("Open the command palette")).toBeInTheDocument();
  });

  it("calls onClose when Close is clicked", () => {
    const onClose = vi.fn();
    render(<KeyboardShortcutsModal open onClose={onClose} />);
    fireEvent.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalled();
  });
});
