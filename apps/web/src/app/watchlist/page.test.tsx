import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { authMock, loadWatchlistPage, readPrint, refresh } = vi.hoisted(() => ({
  authMock: vi.fn(),
  loadWatchlistPage: vi.fn(),
  readPrint: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ auth: authMock }));
vi.mock("@/lib/collectionServer", () => ({ loadWatchlistPage }));
vi.mock("@/lib/publicServer", () => ({ readPrint }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }), usePathname: () => "/watchlist" }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <header data-testid="app-header" /> }));

import type { WatchEntry, WatchlistResponse } from "@/lib/watchlist";

import WatchlistPage, { metadata } from "./page";

const COLLECTOR = { user: { id: "google-123", email: "nami@example.com", name: "Nami" }, sessionKind: "collector" };

const print = (id: number, code: string, name: string) => ({
  card_print_id: id,
  card_code: code,
  name_en: name,
  name_jp: null,
  treatment: "parallel",
  official_asset_variant: "p1",
  release_product_id: 201,
  release_code: "OP-01",
  release_name: "Romance Dawn",
});

const entry = (over: Partial<WatchEntry>): WatchEntry => ({
  id: 1,
  card_print_id: 105,
  resolution: "exact",
  target_jpy: null,
  note: null,
  legacy_card_id: null,
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z",
  print: print(105, "OP01-120", "Shanks"),
  value_status: "priced",
  value_jpy: 31200,
  target_gap_jpy: null,
  checked_at: null,
  change_7d_pct: null,
  change_7d_reason: null,
  ...over,
});

const ENTRIES: WatchEntry[] = [
  entry({ id: 1, target_jpy: 30000, target_gap_jpy: 1200, checked_at: "2026-10-15T09:00:00Z", change_7d_pct: "4.20" }),
  entry({ id: 2, card_print_id: 111, print: print(111, "OP06-118", "Roronoa Zoro"), value_jpy: 28800, target_jpy: 32000, target_gap_jpy: -3200, change_7d_pct: "-6.75" }),
  entry({ id: 3, card_print_id: 115, print: print(115, "OP06-069", "Sanji"), value_status: "no_price", value_jpy: null, target_jpy: 1500, change_7d_reason: "leaver" }),
  entry({ id: 4, card_print_id: 109, print: print(109, "OP03-122", "Sogeking"), value_jpy: 3740, change_7d_reason: "contributor_set_changed" }),
  entry({ id: 5, card_print_id: null, resolution: "unresolved", print: null, value_status: "unresolved", value_jpy: null, target_jpy: 5000, note: "From the old wishlist", legacy_card_id: 3, change_7d_reason: "unresolved" }),
];

function okPage(over: Partial<WatchlistResponse> = {}) {
  return {
    state: "ok",
    watchlist: { currency: "JPY", as_of: "2026-10-14", entries: ENTRIES, change_7d_from: "2026-10-07", change_7d_missing_dates: [], ...over },
  };
}

async function renderPage() {
  return render(await WatchlistPage());
}

function rowFor(name: string) {
  return screen.getAllByTestId("watchlist-row").find((row) => within(row).queryByRole("heading", { name: new RegExp(name) }))!;
}

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("/watchlist (Collector v1 S8)", () => {
  it("is titled 'Cards you're watching'", async () => {
    expect(metadata.title).toBe("Cards you're watching");
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Cards you’re watching" })).toBeInTheDocument();
    expect(screen.getByText(/5 versions/)).toHaveTextContent("Prices as of 14 Oct");
  });

  it("shows each version's value with its date and the distance to its target, from the API", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    const shanks = rowFor("Shanks");
    expect(shanks).toHaveTextContent("￥31,200 as of 14 Oct");
    expect(within(shanks).getByTestId("target-distance")).toHaveTextContent("￥1,200 above your target");
    expect(within(rowFor("Roronoa Zoro")).getByTestId("target-distance")).toHaveTextContent("￥3,200 below your target");
    expect(rowFor("Sogeking")).toHaveTextContent("No target set");
  });

  it("shows an unpriced version as unpriced, never ¥0, with no distance", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    const sanji = rowFor("Sanji");
    expect(sanji).toHaveTextContent("No price yet");
    expect(sanji).not.toHaveTextContent("￥0");
    expect(within(sanji).queryByTestId("target-distance")).toBeNull();
  });

  it("shows the 7D change, and an unavailable one as — with its reason, never 0%", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(rowFor("Shanks")).toHaveTextContent("+4.2%");
    expect(rowFor("Roronoa Zoro")).toHaveTextContent("−6.8%");
    const sogeking = rowFor("Sogeking");
    expect(sogeking).toHaveTextContent("— Price sources changed this week");
    expect(sogeking).not.toHaveTextContent("0%");
    expect(rowFor("Sanji")).toHaveTextContent("— No price today");
  });

  it("says when a source was last checked, and unknown when the API does not know", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-15T12:00:00Z"));
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(within(rowFor("Shanks")).getByTestId("checked")).toHaveTextContent("Checked 3 h ago");
    expect(within(rowFor("Sogeking")).getByTestId("checked")).toHaveTextContent("Check time unknown");
  });

  it("lists a watch that still needs a version separately, with its target", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    const needs = screen.getByRole("heading", { name: "Needs a version" }).closest("section")!;
    expect(needs).toHaveTextContent("Target ￥5,000 · From the old wishlist");
    expect(screen.getAllByTestId("watchlist-row")).toHaveLength(4);
  });

  it("explains a window gap in words for every version", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(
      okPage({
        entries: [entry({ change_7d_reason: "prices_missing" })],
        change_7d_missing_dates: ["2026-10-09"],
      }),
    );
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(rowFor("Shanks")).toHaveTextContent("— Prices missing on 9 Oct");
  });

  it("edits the target in a sheet and refreshes from the API", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /^Edit Shanks/ }));
    const dialog = screen.getByRole("dialog", { name: "Edit your watch" });
    const target = within(dialog).getByLabelText(/Target price/) as HTMLInputElement;
    expect(target.value).toBe("30000");
    fireEvent.change(target, { target: { value: "28000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/me/watchlist/1", expect.objectContaining({ method: "PATCH" }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ target_jpy: 28000 });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("invites the collector to find a card when nothing is watched", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage({ entries: [] }));
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "You’re not watching any cards yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Find a card" })).toHaveAttribute("href", "/cards");
  });

  it.each([
    ["disabled", "Watchlists aren’t switched on yet"],
    ["error", "We couldn’t load your watchlist"],
  ])("renders the %s state plainly", async (state, heading) => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce({ state });
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("asks a visitor to sign in without reading the API", async () => {
    authMock.mockResolvedValueOnce(null);
    await renderPage();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in?callbackUrl=%2Fwatchlist");
    expect(loadWatchlistPage).not.toHaveBeenCalled();
  });

  it("uses watchlist words only", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadWatchlistPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage();
    expect(container.textContent).not.toMatch(/portfolio|P\/L|cost basis|liquidation|\bhold\b|\bsell\b|position|ROI|wishlist analytics|alert/i);
  });
});
