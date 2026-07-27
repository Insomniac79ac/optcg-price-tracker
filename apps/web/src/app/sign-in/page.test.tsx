import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/sign-in",
}));

const { fetchSavedViews } = vi.hoisted(() => ({
  fetchSavedViews: vi.fn().mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSavedViews };
});

import SignInPage from "./page";

const ORIGINAL_ENV = { ...process.env };

describe("SignInPage (neutral sign-in-required route)", () => {
  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
    delete process.env.AUTH_GOOGLE_ID;
    delete process.env.AUTH_GOOGLE_SECRET;
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("explains that collector accounts are not enabled when Google OAuth is unconfigured", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByText(/collector accounts are not enabled in this staging build/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in with google/i })).not.toBeInTheDocument();
  });

  it("treats the documented change-me placeholder as unconfigured, not real credentials", async () => {
    process.env.AUTH_GOOGLE_ID = "change-me";
    process.env.AUTH_GOOGLE_SECRET = "change-me";
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByText(/collector accounts are not enabled/i)).toBeInTheDocument();
  });

  it("shows the Google sign-in action once real credentials are configured", async () => {
    process.env.AUTH_GOOGLE_ID = "real-client-id";
    process.env.AUTH_GOOGLE_SECRET = "real-client-secret";
    const ui = await SignInPage({ searchParams: Promise.resolve({ callbackUrl: "/collection" }) });
    render(ui);
    expect(screen.getByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
  });

  it("contains no admin-login functionality", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/admin token/i)).not.toBeInTheDocument();
  });

  it("links back to Discover and Cards", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByRole("link", { name: /back to discover/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /browse cards/i })).toHaveAttribute("href", "/cards");
  });

  it("never renders a raw environment-variable value into the page", async () => {
    process.env.AUTH_GOOGLE_ID = "super-secret-client-id-value";
    process.env.AUTH_GOOGLE_SECRET = "super-secret-client-secret-value";
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    const { container } = render(ui);
    expect(container.innerHTML).not.toContain("super-secret-client-id-value");
    expect(container.innerHTML).not.toContain("super-secret-client-secret-value");
  });
});
