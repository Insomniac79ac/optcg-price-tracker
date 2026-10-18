import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CollectorShelf, HeldVersion, WatchedVersion } from "@/lib/collectorShelf";

import { parseYen, PrintCollectorActions } from "./PrintCollectorActions";

const LABEL = "Roronoa Zoro (OP01-025) · Alternate art · Found in OP-01";
const BANNED = /portfolio|p\/l|cost basis|liquidat|\bhold\b|\bsell\b|position|roi\b/i;

function shelf(
  status: CollectorShelf["status"],
  held: [number, HeldVersion][] = [],
  watched: [number, WatchedVersion][] = [],
): CollectorShelf {
  return { status, held: new Map(held), watched: new Map(watched), refresh: vi.fn() };
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 1 }), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined };
}

describe("PrintCollectorActions", () => {
  it("invites a visitor to sign in and come back to this exact version", () => {
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={shelf("visitor")} />);
    const link = screen.getByRole("link", { name: "Sign in to add it" });
    expect(link).toHaveAttribute("href", "/sign-in?callbackUrl=%2Fprints%2F5");
    expect(screen.queryByRole("button", { name: "Add to collection" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders nothing when collector accounts are switched off", () => {
    const { container } = render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={shelf("disabled")} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers a retry when the collection could not be read", () => {
    const failed = shelf("error");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={failed} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(failed.refresh).toHaveBeenCalled();
  });

  it("adds this exact version with quantity, what was paid and the date", async () => {
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    expect(screen.getByText("Not in your collection yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    expect(screen.getByText(LABEL)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("How many"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/what you paid per card/i), { target: { value: "¥1,200" } });
    fireEvent.change(screen.getByLabelText(/when you got it/i), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall()).toEqual({
      url: "/api/me/collection",
      method: "POST",
      body: { card_print_id: 5, quantity: 2, paid_jpy_per_card: 1200, acquired_on: "2026-10-01" },
    });
  });

  it("sends blank optional fields as not given, never as zero", async () => {
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall().body).toEqual({ card_print_id: 5, quantity: 1, paid_jpy_per_card: null, acquired_on: null });
  });

  it.each([
    ["How many", "0", /from 1 to 9,999/],
    ["How many", "1.5", /from 1 to 9,999/],
    ["How many", "10000", /from 1 to 9,999/],
    [/what you paid per card/i, "abc", /whole number of yen/],
    [/what you paid per card/i, "-5", /whole number of yen/],
  ])("refuses %s = %s without a request", (label, value, message) => {
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={shelf("ready")} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows what is owned and edits that entry", async () => {
    const ready = shelf("ready", [[5, { entryId: 77, quantity: 2, paidJpyPerCard: 1200, acquiredOn: null }]]);
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    expect(screen.getByTestId("in-collection")).toHaveTextContent("In your collection ×2");
    expect(screen.getByTestId("in-collection")).toHaveTextContent("You paid ￥1,200 each");
    fireEvent.click(screen.getByRole("button", { name: "Edit in collection" }));
    expect(screen.getByLabelText("How many")).toHaveValue("2");
    fireEvent.change(screen.getByLabelText("How many"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall()).toEqual({
      url: "/api/me/collection/77",
      method: "PATCH",
      body: { quantity: 3, paid_jpy_per_card: 1200, acquired_on: null },
    });
  });

  it("removes only after a second, explicit confirmation", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const ready = shelf("ready", [[5, { entryId: 77, quantity: 1, paidJpyPerCard: null, acquiredOn: null }]]);
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit in collection" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove from collection" }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove it" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall()).toEqual({ url: "/api/me/collection/77", method: "DELETE", body: undefined });
  });

  it("watches with an optional target price", async () => {
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    fireEvent.change(screen.getByLabelText(/target price/i), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall()).toEqual({ url: "/api/me/watchlist", method: "POST", body: { card_print_id: 5, target_jpy: 5000 } });
  });

  it("shows what is typed with commas and sends plain numbers", async () => {
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    const paid = screen.getByLabelText(/what you paid per card/i) as HTMLInputElement;
    fireEvent.change(paid, { target: { value: "30000" } });
    expect(paid.value).toBe("30,000");
    fireEvent.change(screen.getByLabelText("How many"), { target: { value: "１２" } });
    expect((screen.getByLabelText("How many") as HTMLInputElement).value).toBe("12");
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall().body).toEqual({ card_print_id: 5, quantity: 12, paid_jpy_per_card: 30000, acquired_on: null });
  });

  it("sends a grouped target as a plain number", async () => {
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    const target = screen.getByLabelText(/target price/i) as HTMLInputElement;
    fireEvent.change(target, { target: { value: "¥5,000" } });
    expect(target.value).toBe("5,000");
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall().body).toEqual({ card_print_id: 5, target_jpy: 5000 });
  });

  it("keeps the quantity and yen limits", () => {
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={shelf("ready")} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    const quantity = screen.getByLabelText("How many") as HTMLInputElement;
    fireEvent.change(quantity, { target: { value: "10000" } });
    expect(quantity.value).toBe("10,000");
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    expect(screen.getByRole("alert")).toHaveTextContent("from 1 to 9,999");
    fireEvent.change(quantity, { target: { value: "9,999" } });
    fireEvent.change(screen.getByLabelText(/what you paid per card/i), { target: { value: "100,000,001" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/whole number of yen/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a zero target price", () => {
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={shelf("ready")} />);
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    fireEvent.change(screen.getByLabelText(/target price/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Watch" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/above zero/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a watch and can stop it", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const ready = shelf("ready", [], [[5, { entryId: 9, targetJpy: null }]]);
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    expect(screen.getByTestId("watching")).toHaveTextContent("No target price");
    fireEvent.click(screen.getByRole("button", { name: "Edit watch" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop watching" }));
    await waitFor(() => expect(ready.refresh).toHaveBeenCalled());
    expect(lastCall()).toEqual({ url: "/api/me/watchlist/9", method: "DELETE", body: undefined });
  });

  it("says plainly when the sign-in has ended", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ error: "Sign-in required" }), { status: 401 }));
    const ready = shelf("ready");
    render(<PrintCollectorActions cardPrintId={5} versionLabel={LABEL} shelf={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/sign-in has ended/i);
    expect(ready.refresh).not.toHaveBeenCalled();
  });

  it("uses collection language only", () => {
    const { container } = render(
      <PrintCollectorActions
        cardPrintId={5}
        versionLabel={LABEL}
        shelf={shelf("ready", [[5, { entryId: 1, quantity: 1, paidJpyPerCard: 10, acquiredOn: null }]], [[5, { entryId: 2, targetJpy: 9 }]])}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit in collection" }));
    expect(container.textContent).not.toMatch(BANNED);
  });
});

describe("parseYen", () => {
  it.each([
    ["", null],
    ["  ", null],
    ["1200", 1200],
    ["¥1,200", 1200],
    ["１，２００円", 1200],
    ["0", 0],
  ])("reads %j as %j", (raw, expected) => expect(parseYen(raw, { allowZero: true })).toBe(expected));
  it.each(["1.5", "-1", "1e3", "100000001", "abc"])("rejects %j", (raw) => expect(parseYen(raw, { allowZero: true })).toBe("invalid"));
  it("rejects zero where zero is meaningless", () => expect(parseYen("0", { allowZero: false })).toBe("invalid"));
});
