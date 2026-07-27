import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useSessionMock = vi.fn();
vi.mock("next-auth/react", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

import { SidebarNav } from "./SidebarNav";

const INTERNAL_TRADING_LABELS = [
  "Opportunities",
  "Signals",
  "Signal events",
  "Report",
  "Buy Decisions",
  "Sell Decisions",
  "Portfolio Risk",
  "Analytics Digest",
  "Collection Analytics",
  "Wishlist Analytics",
  "Grading Analytics",
];

describe("SidebarNav - signed out", () => {
  beforeEach(() => {
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
  });

  it("shows only Discover, Cards and Market Index", () => {
    render(<SidebarNav />);
    expect(screen.getByText("Discover")).toBeInTheDocument();
    expect(screen.getByText("Cards")).toBeInTheDocument();
    expect(screen.getByText("Market Index")).toBeInTheDocument();
  });

  it("does not show collector-authenticated links", () => {
    render(<SidebarNav />);
    expect(screen.queryByText("My Collection")).not.toBeInTheDocument();
    expect(screen.queryByText("Wishlist")).not.toBeInTheDocument();
    expect(screen.queryByText("Grading")).not.toBeInTheDocument();
    expect(screen.queryByText("Activity")).not.toBeInTheDocument();
  });

  it("shows no Admin or Admin · More sections", () => {
    render(<SidebarNav />);
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
    expect(screen.queryByText(/admin.*more/i)).not.toBeInTheDocument();
  });

  it("shows none of the internal/trading-terminal routes", () => {
    render(<SidebarNav />);
    for (const label of INTERNAL_TRADING_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});

describe("SidebarNav - signed in (collector session)", () => {
  beforeEach(() => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
  });

  it("still shows the public tier", () => {
    render(<SidebarNav />);
    expect(screen.getByText("Discover")).toBeInTheDocument();
    expect(screen.getByText("Cards")).toBeInTheDocument();
    expect(screen.getByText("Market Index")).toBeInTheDocument();
  });

  it("additionally shows My Collection, Wishlist, Grading and Activity", () => {
    render(<SidebarNav />);
    expect(screen.getByText("My Collection")).toBeInTheDocument();
    expect(screen.getByText("Wishlist")).toBeInTheDocument();
    expect(screen.getByText("Grading")).toBeInTheDocument();
    expect(screen.getByText("Activity")).toBeInTheDocument();
  });

  it("still shows no Admin sections for an ordinary collector session", () => {
    render(<SidebarNav />);
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
    expect(screen.queryByText(/admin.*more/i)).not.toBeInTheDocument();
  });

  it("still shows none of the internal/trading-terminal routes", () => {
    render(<SidebarNav />);
    for (const label of INTERNAL_TRADING_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});

describe("SidebarNav - signed in (admin session)", () => {
  beforeEach(() => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "admin@example.com", role: "admin" } },
      status: "authenticated",
    });
  });

  it("shows exactly one Admin entry, not the detailed admin route list", () => {
    render(<SidebarNav />);
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
    expect(screen.queryByText("Catalog Ops")).not.toBeInTheDocument();
    expect(screen.queryByText("Cache")).not.toBeInTheDocument();
  });
});
