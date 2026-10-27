import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next-auth's useSession() without a <SessionProvider> returns undefined in production
// (it throws only in development). That is what Next.js hands the 404 page for an
// unrecognised server-action POST, which renders not-found.tsx without the root layout.
let providerValue: unknown;
vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => providerValue),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import NotFound from "@/app/not-found";
import { useCollectorSession } from "./useCollectorSession";

function Probe() {
  const { data, status } = useCollectorSession();
  return <p>{`${status}:${data?.user?.email ?? "none"}`}</p>;
}

describe("useCollectorSession", () => {
  beforeEach(() => {
    providerValue = undefined;
  });

  it("reads as signed out when no SessionProvider is mounted", () => {
    render(<Probe />);
    expect(screen.getByText("unauthenticated:none")).toBeInTheDocument();
  });

  it("passes the provider's session through unchanged", () => {
    providerValue = { data: { user: { email: "a@example.com" } }, status: "authenticated", update: vi.fn() };
    render(<Probe />);
    expect(screen.getByText("authenticated:a@example.com")).toBeInTheDocument();
  });

  it("renders the 404 page with its real shell and no provider, signed out", () => {
    // Server render, as Next.js does for `POST /` with an unknown Next-Action header.
    const html = renderToString(<NotFound />);
    expect(html).toContain("This chart doesn");
    expect(html).toContain("data-app-header");
    render(<NotFound />);
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
  });
});
