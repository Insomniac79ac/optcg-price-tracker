import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => { throw new Error(`NEXT_REDIRECT ${url}`); },
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

const { authMock } = vi.hoisted(() => ({ authMock: vi.fn().mockResolvedValue(null) }));
vi.mock("@/lib/auth", () => ({ auth: authMock }));

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

  it("says sign-in is not open yet, without a dead end, when Google OAuth is unconfigured", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByText(/collector sign-in is not open yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing to sign in to/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in with google/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /look up card prices/i })).toHaveAttribute("href", "/cards");
    // The public MVP must not describe itself as a staging build, and must not
    // promise when accounts arrive.
    expect(screen.queryByText(/staging/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/check back/i)).not.toBeInTheDocument();
  });

  it("leads with what an account is for and that browsing needs none", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByRole("heading", { level: 1, name: /track what your cards are worth/i })).toBeInTheDocument();
    expect(screen.getByText(/sign in with google to start a collection/i)).toBeInTheDocument();
    expect(screen.getByText(/with or without an account/i)).toBeInTheDocument();
    // Grading was deleted in S1; the invite must not offer it.
    expect(screen.queryByText(/grading/i)).not.toBeInTheDocument();
  });

  it("treats the documented change-me placeholder as unconfigured, not real credentials", async () => {
    process.env.AUTH_GOOGLE_ID = "change-me";
    process.env.AUTH_GOOGLE_SECRET = "change-me";
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByText(/collector sign-in is not open yet/i)).toBeInTheDocument();
  });

  it("shows the Google sign-in action and the invite-only note once real credentials are configured", async () => {
    process.env.AUTH_GOOGLE_ID = "real-client-id";
    process.env.AUTH_GOOGLE_SECRET = "real-client-secret";
    const ui = await SignInPage({ searchParams: Promise.resolve({ callbackUrl: "/collection" }) });
    render(ui);
    expect(screen.getByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
    expect(screen.getByText(/invite-only while accounts are being tested/i)).toBeInTheDocument();
  });

  it("contains no admin-login functionality for a signed-out visitor", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/admin token/i)).not.toBeInTheDocument();
  });

  it("tells an admin session that collection pages need a Google collector account", async () => {
    authMock.mockResolvedValueOnce({ user: { email: "admin@example.com", role: "admin" }, sessionKind: "admin" });
    process.env.AUTH_GOOGLE_ID = "real-client-id";
    process.env.AUTH_GOOGLE_SECRET = "real-client-secret";
    const ui = await SignInPage({ searchParams: Promise.resolve({ callbackUrl: "/collection" }) });
    render(ui);
    expect(screen.getByText(/signed in as the site admin/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
  });

  it("offers an expired admin session plain Google sign-in, with no admin note", async () => {
    authMock.mockResolvedValueOnce({
      user: { email: "admin@example.com" },
      sessionKind: "admin",
      adminSessionExpired: true,
    });
    process.env.AUTH_GOOGLE_ID = "real-client-id";
    process.env.AUTH_GOOGLE_SECRET = "real-client-secret";
    const ui = await SignInPage({ searchParams: Promise.resolve({ callbackUrl: "/collection" }) });
    const { container } = render(ui);
    expect(screen.getByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
    expect(container.querySelector("[data-admin-note]")).toBeNull();
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });

  it("links on to the public pages", async () => {
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    render(ui);
    const browse = within(screen.getByRole("navigation", { name: /keep browsing/i }));
    expect(browse.getByRole("link", { name: /^home$/i })).toHaveAttribute("href", "/");
    expect(browse.getByRole("link", { name: /follow the market/i })).toHaveAttribute("href", "/analytics");
  });

  it("never renders a raw environment-variable value into the page", async () => {
    process.env.AUTH_GOOGLE_ID = "super-secret-client-id-value";
    process.env.AUTH_GOOGLE_SECRET = "super-secret-client-secret-value";
    const ui = await SignInPage({ searchParams: Promise.resolve({}) });
    const { container } = render(ui);
    expect(container.innerHTML).not.toContain("super-secret-client-id-value");
    expect(container.innerHTML).not.toContain("super-secret-client-secret-value");
  });

  it("sends an already signed-in collector on to the requested page", async () => {
    authMock.mockResolvedValueOnce({ user: { email: "c@example.com" }, sessionKind: "collector" });
    await expect(SignInPage({ searchParams: Promise.resolve({ callbackUrl: "/account" }) })).rejects.toThrow("NEXT_REDIRECT /account");
  });
});
