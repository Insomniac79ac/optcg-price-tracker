import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CollectionValue, Coverage } from "@/lib/collection";
import type { WatchEntry, WatchlistResponse } from "@/lib/watchlist";

import { OverviewStrip } from "./OverviewStrip";

const coverage = (over: Partial<Coverage> = {}): Coverage => ({
  value_jpy: 248000,
  priced_cards: 14,
  total_cards: 14,
  priced_entries: 9,
  total_entries: 9,
  unresolved_entries: 0,
  coverage_pct: "100",
  ...over,
});

const change = (over: Partial<CollectionValue["history"]["change"]> = {}) => ({
  window: "7d",
  available: true,
  reason: null,
  from_date: "2026-10-10",
  to_date: "2026-10-17",
  change_pct: "2.4",
  missing_dates: [],
  ...over,
});

const value = (summary: Partial<Coverage> = {}, history = change()): CollectionValue =>
  ({ as_of: "2026-10-17", window: "7d", summary: coverage(summary), history: { change: history, points: [] } }) as unknown as CollectionValue;

const watch = (over: Partial<WatchEntry> = {}): WatchEntry => ({
  id: 1,
  card_print_id: 105,
  resolution: "exact",
  target_jpy: null,
  note: null,
  legacy_card_id: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  print: null,
  value_status: "priced",
  value_jpy: 1000,
  target_gap_jpy: null,
  ...over,
});

const PRINT = { card_print_id: 105, card_code: "OP02-013", name_en: "Portgas.D.Ace", name_jp: null, treatment: null, official_asset_variant: null, release_product_id: null, release_code: null, release_name: null };

const list = (entries: WatchEntry[]): WatchlistResponse => ({ currency: "JPY", as_of: "2026-10-17", entries });

function tile(key: string) {
  const link = document.querySelector(`[data-tile="${key}"]`) as HTMLAnchorElement;
  expect(link).not.toBeNull();
  return { link, text: link.textContent ?? "", within: within(link) };
}

describe("OverviewStrip", () => {
  it("shows value with its 7D change, cards, watches and the closest watch, each linking on", () => {
    render(
      <OverviewStrip
        collection={value()}
        watchlist={list([
          watch({ id: 1, target_jpy: 500, target_gap_jpy: 50 }),
          watch({ id: 2, target_jpy: 30000, target_gap_jpy: -600, print: PRINT }),
          watch({ id: 3 }),
        ])}
      />,
    );
    expect(screen.getAllByRole("link")).toHaveLength(4);

    const v = tile("value");
    expect(v.link).toHaveAttribute("href", "/collection");
    expect(v.text).toContain("Collection value");
    expect(v.text).toContain("￥248,000");
    expect(v.within.getByText("+2.4% 7D")).toHaveAttribute("data-direction", "up");

    const cards = tile("cards");
    expect(cards.link).toHaveAttribute("href", "/collection");
    expect(cards.text).toContain("14 cards");
    expect(cards.text).toContain("9 versions");

    const watching = tile("watching");
    expect(watching.link).toHaveAttribute("href", "/watchlist");
    expect(watching.text).toContain("3 cards");
    expect(watching.text).toContain("2 with a target");

    const closest = tile("closest");
    expect(closest.link).toHaveAttribute("href", "/watchlist");
    expect(closest.text).toContain("Portgas.D.Ace");
    expect(closest.text).toContain("￥600 below your target");
  });

  it("gives the reason instead of a 7D change, and counts priced cards when some are not", () => {
    render(<OverviewStrip collection={value({ priced_cards: 11 }, change({ available: false, reason: "not_enough_history", change_pct: null }))} watchlist={list([])} />);
    expect(tile("value").text).toContain("7D: Not enough history yet");
    expect(tile("value").text).not.toContain("0%");
    expect(tile("cards").text).toContain("11 priced");
  });

  it("says so for zero cards and zero watches", () => {
    render(<OverviewStrip collection={value({ value_jpy: null, priced_cards: 0, total_cards: 0, total_entries: 0, priced_entries: 0 })} watchlist={list([])} />);
    expect(tile("value").text).toContain("No cards yet");
    expect(tile("value").text).not.toContain("￥0");
    expect(tile("cards").text).toContain("0 cards");
    expect(tile("cards").text).toContain("Your collection is empty");
    expect(tile("watching").text).toContain("0 cards");
    expect(tile("closest").text).toContain("No watches yet");
    expect(tile("value").link).toHaveAttribute("href", "/collection");
    expect(tile("closest").link).toHaveAttribute("href", "/watchlist");
  });

  it("never shows ¥0 for cards without prices", () => {
    render(<OverviewStrip collection={value({ value_jpy: null, priced_cards: 0 }, change({ available: false, reason: "no_prices_yet", change_pct: null }))} watchlist={list([])} />);
    expect(tile("value").text).toContain("No prices yet");
    expect(tile("value").text).not.toContain("￥0");
  });

  it("separates watches without targets from targets without prices", () => {
    const { unmount } = render(<OverviewStrip collection={value()} watchlist={list([watch(), watch({ id: 2 })])} />);
    expect(tile("watching").text).toContain("No targets set");
    expect(tile("closest").text).toContain("No targets set");
    unmount();
    render(<OverviewStrip collection={value()} watchlist={list([watch({ target_jpy: 5000, value_status: "no_price", value_jpy: null })])} />);
    expect(tile("closest").text).toContain("No prices yet");
  });

  it("keeps the tiles and says not available when a read failed", () => {
    render(<OverviewStrip collection={null} watchlist={null} />);
    expect(screen.getAllByRole("link")).toHaveLength(4);
    for (const key of ["value", "cards", "watching", "closest"]) expect(tile(key).text).toContain("Not available right now");
  });
});
