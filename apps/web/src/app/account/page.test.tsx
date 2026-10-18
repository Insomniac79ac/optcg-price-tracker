import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { authMock, loadAccountOverview, signOut } = vi.hoisted(() => ({
  authMock: vi.fn(),
  loadAccountOverview: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ auth: authMock }));
vi.mock("@/lib/accountServer", () => ({ loadAccountOverview }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: null, status: "unauthenticated" }), signIn: vi.fn(), signOut }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/account" }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <header data-testid="app-header" /> }));

import AccountPage from "./page";

const COLLECTOR = { user: { id: "google-123", email: "nami@example.com", name: "Nami" }, sessionKind: "collector" };
const OK = {
  state: "ok",
  profile: { email: "nami@example.com", name: "Nami", member_since: "2026-10-14T12:00:00Z" },
  preferences: { currency: "JPY", collection_visibility: "private" },
  collection: null,
  watchlist: { currency: "JPY", as_of: null, entries: [] },
};

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("/account", () => {
  it("shows profile, currency, export and delete for a collector", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce(OK);
    render(await AccountPage());

    expect(screen.getByRole("heading", { level: 1, name: "Nami" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByText(/managed by google/i)).toBeInTheDocument();
    expect(screen.getByText("Oct 14, 2026")).toBeInTheDocument();

    const currency = screen.getByLabelText("Currency") as HTMLSelectElement;
    expect(currency.value).toBe("JPY");
    const options = within(currency).getAllByRole("option") as HTMLOptionElement[];
    expect(options.filter((o) => !o.disabled).map((o) => o.value)).toEqual(["JPY"]);
    expect(options.filter((o) => o.disabled).length).toBeGreaterThan(0);

    expect(screen.getByRole("link", { name: /all data \(json\)/i })).toHaveAttribute("href", "/api/me/export");
    expect(screen.getByRole("link", { name: /collection \(csv\)/i })).toHaveAttribute("href", "/api/me/export/collection.csv");
    expect(screen.getByRole("link", { name: /watchlist \(csv\)/i })).toHaveAttribute("href", "/api/me/export/watchlist.csv");
    expect(screen.getByRole("button", { name: /delete my account/i })).toBeDisabled();
    expect(loadAccountOverview).toHaveBeenCalledWith({ sub: "google-123", email: "nami@example.com", name: "Nami" });
  });

  it("opens with the overview strip, above the profile", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce(OK);
    render(await AccountPage());
    const strip = screen.getByRole("region", { name: "Overview" });
    expect(within(strip).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/collection", "/collection", "/watchlist", "/watchlist"]);
    expect(within(strip).getByText("No watches yet")).toBeInTheDocument();
    expect(strip.compareDocumentPosition(screen.getByRole("heading", { name: "Profile" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([["ok", OK], ["accounts off", { state: "disabled" }], ["a failed load", { state: "error" }]])(
    "leaves Sign out to the header (%s)",
    async (_label, overview) => {
      authMock.mockResolvedValueOnce(COLLECTOR);
      loadAccountOverview.mockResolvedValueOnce(overview);
      render(await AccountPage());
      expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
      expect(screen.queryByText(/^sign out$/i)).not.toBeInTheDocument();
    },
  );

  it("shows no overview strip when accounts are off", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce({ state: "disabled" });
    render(await AccountPage());
    expect(screen.queryByRole("region", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("renders no token or secret into the page", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce(OK);
    const { container } = render(await AccountPage());
    expect(container.innerHTML).not.toMatch(/Bearer|eyJ|apiToken/);
  });

  it("deletes only after the exact typed confirmation, then signs out", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce(OK);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    render(await AccountPage());

    const button = screen.getByRole("button", { name: /delete my account/i });
    fireEvent.change(screen.getByLabelText(/to confirm/i), { target: { value: "delete my acc" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/to confirm/i), { target: { value: "delete my account" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/" }));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/me?confirm=delete%20my%20account");
    expect(init).toMatchObject({ method: "DELETE", credentials: "same-origin" });
    expect(init.headers).toBeUndefined();
  });

  it("keeps the session and says so when the delete fails", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce(OK);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 500 })));
    render(await AccountPage());
    fireEvent.change(screen.getByLabelText(/to confirm/i), { target: { value: "delete my account" } });
    fireEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/was not deleted/i);
    expect(signOut).not.toHaveBeenCalled();
  });

  it("says plainly when collector accounts are switched off", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadAccountOverview.mockResolvedValueOnce({ state: "disabled" });
    render(await AccountPage());
    expect(screen.getByText(/not switched on yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete my account/i })).not.toBeInTheDocument();
  });

  it.each([["signed out", null], ["an admin session", { user: { id: "staging-admin", email: "a@example.com", role: "admin" }, sessionKind: "admin" }]])(
    "never loads account data for %s",
    async (_label, session) => {
      authMock.mockResolvedValueOnce(session);
      render(await AccountPage());
      expect(loadAccountOverview).not.toHaveBeenCalled();
      expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/sign-in?callbackUrl=%2Faccount");
    },
  );
});
