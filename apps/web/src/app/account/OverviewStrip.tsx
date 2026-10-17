import Link from "next/link";

import { accountSurfaceStyles as styles } from "@/components/ui/AccountSurface";
import { cardName, direction, signedPct, unavailableReason, yen, type CollectionValue } from "@/lib/collection";
import { closestToTarget, targetDistance, type WatchlistResponse } from "@/lib/watchlist";

const UNAVAILABLE = "Not available right now";

interface Tile {
  key: string;
  href: "/collection" | "/watchlist";
  label: string;
  value: string;
  detail: string;
  direction?: "up" | "down" | "flat";
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString("en")} ${count === 1 ? one : many}`;
}

/** Collection value with its 7D change, the same figure as the 7D chip on
 * /collection. Never ¥0 for a collection without prices. */
function valueTile(collection: CollectionValue | null): Tile {
  const base = { key: "value", href: "/collection", label: "Collection value" } as const;
  if (!collection) return { ...base, value: UNAVAILABLE, detail: "Open your collection" };
  const { summary, history } = collection;
  if (summary.total_cards === 0) return { ...base, value: "No cards yet", detail: "Add one from any card page" };
  if (summary.value_jpy === null) return { ...base, value: "No prices yet", detail: `7D: ${unavailableReason(history.change)}` };
  const pct = history.change.available ? signedPct(history.change.change_pct) : null;
  return pct
    ? { ...base, value: yen(summary.value_jpy), detail: `${pct} 7D`, direction: direction(history.change.change_pct) }
    : { ...base, value: yen(summary.value_jpy), detail: `7D: ${unavailableReason(history.change)}` };
}

function cardsTile(collection: CollectionValue | null): Tile {
  const base = { key: "cards", href: "/collection", label: "Cards" } as const;
  if (!collection) return { ...base, value: UNAVAILABLE, detail: "Open your collection" };
  const { summary } = collection;
  if (summary.total_cards === 0) return { ...base, value: "0 cards", detail: "Your collection is empty" };
  const detail =
    summary.priced_cards < summary.total_cards
      ? `${summary.priced_cards.toLocaleString("en")} priced`
      : plural(summary.total_entries, "version", "versions");
  return { ...base, value: plural(summary.total_cards, "card", "cards"), detail };
}

function watchingTile(watchlist: WatchlistResponse | null): Tile {
  const base = { key: "watching", href: "/watchlist", label: "Watching" } as const;
  if (!watchlist) return { ...base, value: UNAVAILABLE, detail: "Open your watchlist" };
  const count = watchlist.entries.length;
  if (count === 0) return { ...base, value: "0 cards", detail: "Watch one from any card page" };
  const targets = watchlist.entries.filter((entry) => entry.target_jpy !== null).length;
  return { ...base, value: plural(count, "card", "cards"), detail: targets === 0 ? "No targets set" : `${targets.toLocaleString("en")} with a target` };
}

/** The watch nearest its target (closestToTarget), described with the same
 * targetDistance words as its row on /watchlist. */
function closestTile(watchlist: WatchlistResponse | null): Tile {
  const base = { key: "closest", href: "/watchlist", label: "Closest to target" } as const;
  if (!watchlist) return { ...base, value: UNAVAILABLE, detail: "Open your watchlist" };
  if (watchlist.entries.length === 0) return { ...base, value: "Nothing watched yet", detail: "Set a target when you watch a card" };
  if (!watchlist.entries.some((entry) => entry.target_jpy !== null)) return { ...base, value: "No targets set", detail: "Add a target price to a watch" };
  const closest = closestToTarget(watchlist.entries);
  const distance = closest ? targetDistance(closest) : null;
  if (!closest || !distance) return { ...base, value: "No prices yet", detail: "None of your targets has a price yet" };
  return { ...base, value: cardName(closest.print), detail: distance };
}

/** The overview strip at the top of /account: what the collector holds and
 * watches, each tile a way into /collection or /watchlist. Every number is
 * the API's (GET /me/collection/value?window=7d and GET /me/watchlist). */
export function OverviewStrip({ collection, watchlist }: { collection: CollectionValue | null; watchlist: WatchlistResponse | null }) {
  const tiles = [valueTile(collection), cardsTile(collection), watchingTile(watchlist), closestTile(watchlist)];
  return (
    <section aria-label="Overview" className={styles.overview}>
      <ul className={styles.tiles} data-testid="account-overview">
        {tiles.map((tile) => (
          <li key={tile.key}>
            <Link href={tile.href} className={styles.tile} data-tile={tile.key}>
              <span className={styles.tileLabel}>{tile.label}</span>
              <span className={styles.tileValue}>{tile.value}</span>
              <span className={styles.tileDetail} data-direction={tile.direction}>{tile.detail}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
