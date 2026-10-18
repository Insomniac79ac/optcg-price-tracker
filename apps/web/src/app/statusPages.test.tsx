import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const appHeader = vi.fn();
vi.mock("@/components/AppHeader", () => ({
  AppHeader: (props: { publicShell?: boolean }) => {
    appHeader(props);
    return <header data-testid="app-header" />;
  },
}));
vi.mock("@/lib/reportError", () => ({ reportError: vi.fn() }));

import GlobalError from "./error";
import NotFound from "./not-found";

describe("404 page", () => {
  it("asks for the public shell, since it renders under any path", () => {
    render(<NotFound />);
    expect(appHeader).toHaveBeenCalledWith(expect.objectContaining({ publicShell: true }));
  });

  it("keeps its message and offers the way back home and to card prices", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This chart doesn’t lead anywhere.");
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Browse card prices" })).toHaveAttribute("href", "/cards");
    expect(document.body.textContent).not.toMatch(/optcg vault|tcg vault|price tracker|portfolio/i);
  });
});

describe("error page", () => {
  it("renders without the shell, retries through reset and links home", () => {
    const reset = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => {});
    appHeader.mockClear();
    render(<GlobalError error={new Error("boom")} reset={reset} />);
    expect(appHeader).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This page couldn’t be loaded.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
    expect(document.body.textContent).not.toMatch(/optcg vault|tcg vault|price tracker/i);
  });
});
