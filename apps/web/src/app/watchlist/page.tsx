import type { Metadata } from "next";
import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { WatchEditSheet } from "@/components/collection/CollectionEditSheet";
import styles from "@/components/collection/Collection.module.css";
import watch from "@/components/collection/Watchlist.module.css";
import { AccountChapter, AccountHero, accountSurfaceStyles as surface } from "@/components/ui/AccountSurface";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { auth } from "@/lib/auth";
import { cardName, shortDate, yen } from "@/lib/collection";
import { loadWatchlistPage } from "@/lib/collectionServer";
import { collectorIdentity } from "@/lib/collectorApi";
import { toPrintUiModel, type PrintUiModel } from "@/lib/prints";
import { readPrint } from "@/lib/publicServer";
import { checkedAgo, targetDistance, watchChange, type WatchEntry, type WatchlistResponse } from "@/lib/watchlist";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Cards you're watching" };

const LINK = "inline-flex min-h-11 items-center rounded-control border border-[#3e696a] px-4 text-sm font-medium text-[#8dc9c4] transition-colors hover:border-accent-teal hover:text-text-primary";

/** The signed-in collector's watchlist (Collector v1 S8, PLAN §E3), read
 * server-side from the v1 accounts API. One row per watched version: art,
 * version, today's value with its date, how far it is from the target, when a
 * source was last checked and the 7D change.
 *
 * Every number is the API's: an unpriced version reads "No price yet", an
 * unknown check time reads unknown, and a 7D change the API could not publish
 * shows "—" with the reason, never 0%. No alerts or emails. src/proxy.ts
 * already sends anyone who is not a collector to /sign-in; the session is
 * checked again here. */
export default async function WatchlistPage() {
  const identity = collectorIdentity(await auth());
  if (!identity) {
    return (
      <Frame>
        <AccountHero>
          <p className={surface.kicker}>Watchlist</p>
          <h1 className={surface.title}>Sign in to see the cards you’re watching</h1>
          <div className={surface.links}>
            <Link href="/sign-in?callbackUrl=%2Fwatchlist" className={LINK}>Sign in</Link>
          </div>
        </AccountHero>
      </Frame>
    );
  }

  const data = await loadWatchlistPage(identity);
  if (data.state !== "ok") {
    return (
      <Frame>
        <AccountHero>
          <p className={surface.kicker}>Watchlist</p>
          <h1 className={surface.title}>{data.state === "disabled" ? "Watchlists aren’t switched on yet" : "We couldn’t load your watchlist"}</h1>
          <p className={surface.supporting}>
            {data.state === "disabled"
              ? "Card prices and the market are still open to browse."
              : "Nothing has changed in it. Please reload the page in a moment."}
          </p>
          <div className={surface.links}>
            {data.state === "error" && <Link href="/watchlist" className={LINK}>Reload</Link>}
            <Link href="/cards" className={LINK}>Browse cards</Link>
          </div>
        </AccountHero>
      </Frame>
    );
  }

  const { watchlist } = data;
  if (watchlist.entries.length === 0) return <EmptyWatchlist />;

  const exact = watchlist.entries.filter((entry) => entry.resolution === "exact" && entry.card_print_id !== null);
  const unresolved = watchlist.entries.filter((entry) => entry.resolution !== "exact" || entry.card_print_id === null);
  const prints = await loadPrints(exact.map((entry) => entry.card_print_id as number));
  const asOf = shortDate(watchlist.as_of);
  const now = new Date();
  const count = watchlist.entries.length;

  return (
    <Frame>
      <AccountHero>
        <p className={surface.kicker}>Watchlist</p>
        <h1 className={surface.title}>Cards you’re watching</h1>
        <p className={styles.asOf}>
          {count} {count === 1 ? "version" : "versions"}
          <span aria-hidden="true"> · </span>
          {asOf ? `Prices as of ${asOf}` : "No daily price check yet"}
        </p>
        <p className={styles.coverageNote}>Set a target price on any version to see how far today’s value is from it. No emails are sent.</p>
      </AccountHero>

      {exact.length > 0 && (
        <section aria-labelledby="watching" className={styles.section}>
          <AccountChapter id="watching" number="01" title="Watching">
            Today’s value, your target and the last 7 days for each version
          </AccountChapter>
          <ul className={watch.grid} data-testid="watchlist-rows">
            {exact.map((entry) => (
              <WatchRow key={entry.id} entry={entry} print={prints.get(entry.card_print_id as number) ?? null} list={watchlist} asOf={asOf} now={now} />
            ))}
          </ul>
        </section>
      )}

      {unresolved.length > 0 && (
        <section aria-labelledby="needs-version" className={styles.section}>
          <AccountChapter id="needs-version" number={exact.length > 0 ? "02" : "01"} title="Needs a version">
            These came from your old wishlist and match more than one version, so they have no price yet.
          </AccountChapter>
          <ul className={styles.needs}>
            {unresolved.map((entry) => (
              <li key={entry.id} className={styles.needsRow}>
                <div className="min-w-0">
                  <p className={styles.needsName}>{entry.print ? cardName(entry.print) : "A card from your old wishlist"}</p>
                  <p className={styles.meta}>
                    {entry.target_jpy !== null ? `Target ${yen(entry.target_jpy)}` : "No target"}
                    {entry.note ? ` · ${entry.note}` : ""}
                  </p>
                </div>
                <div className={styles.needsActions}>
                  <Link href="/cards" className={LINK}>Find the version</Link>
                  <WatchEditSheet
                    entryId={entry.id}
                    cardPrintId={null}
                    versionLabel={entry.note ?? "A card from your old wishlist"}
                    targetJpy={entry.target_jpy}
                    buttonDescription="Edit this card from your old wishlist"
                  />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className={surface.root}>
      <AppHeader />
      <main className={`${surface.main} ${styles.main}`}>{children}</main>
    </div>
  );
}

async function loadPrints(ids: number[]): Promise<Map<number, PrintUiModel>> {
  const unique = [...new Set(ids)];
  const details = await Promise.all(unique.map((id) => readPrint(String(id)).catch(() => null)));
  const map = new Map<number, PrintUiModel>();
  details.forEach((detail, index) => {
    if (detail) map.set(unique[index], toPrintUiModel(detail));
  });
  return map;
}

function EmptyWatchlist() {
  return (
    <Frame>
      <AccountHero>
        <p className={surface.kicker}>Watchlist</p>
        <h1 className={surface.title}>You’re not watching any cards yet</h1>
        <p className={surface.supporting}>
          Find a card, open the exact version you want, and choose “Watch”. Add a target price and this page shows how
          far today’s value is from it.
        </p>
        <div className={surface.links}>
          <Link href="/cards" className={styles.primaryLink}>Find a card</Link>
        </div>
      </AccountHero>
    </Frame>
  );
}

function WatchRow({
  entry,
  print,
  list,
  asOf,
  now,
}: {
  entry: WatchEntry;
  print: PrintUiModel | null;
  list: WatchlistResponse;
  asOf: string | null;
  now: Date;
}) {
  const name = print?.displayName ?? cardName(entry.print);
  const code = print?.cardCode ?? entry.print?.card_code ?? "";
  const label = [code, print?.printingType?.label, print?.releaseCode ?? entry.print?.release_code].filter(Boolean).join(" · ");
  const href = `/prints/${entry.card_print_id}`;
  const distance = targetDistance(entry);
  const change = watchChange(entry, list);
  const priced = entry.value_jpy !== null;
  return (
    <li className={watch.tile} data-testid="watchlist-row">
      <Link href={href} className={styles.tileArt} tabIndex={-1} aria-hidden="true">
        <CardImageFrame
          imageUrl={print?.imageUrl ?? null}
          alt={`${name} (${code})`}
          cardCode={code}
          rarity={print?.rarity ?? null}
          setCode={print?.releaseCode ?? null}
          size="full"
          padded
          geometry={print?.imageGeometry ?? null}
        />
      </Link>
      <div className={`${styles.tileBody} ${watch.body}`}>
        <h3 className={styles.tileName}>
          <Link href={href}>
            {name}
            {print?.printingType && <span className={styles.moverVersion}> · {print.printingType.label}</span>}
          </Link>
        </h3>
        <p className={styles.meta}>{label}</p>

        <p className={styles.tileValue}>
          {priced ? (
            <>
              <span>{yen(entry.value_jpy as number)}</span>
              {asOf && <span className={styles.meta}> · as of {asOf}</span>}
            </>
          ) : (
            <span className={styles.noPrice}>No price yet</span>
          )}
        </p>

        <div className={watch.target}>
          <p>
            <span className={watch.label}>Target</span>{" "}
            {entry.target_jpy !== null ? <span className={watch.targetValue}>{yen(entry.target_jpy)}</span> : <span className={styles.meta}>Not set</span>}
          </p>
          {distance && (
            <p className={watch.distance} data-testid="target-distance" data-side={(entry.target_gap_jpy ?? 0) > 0 ? "above" : "below"}>
              {distance}
            </p>
          )}
        </div>

        {change.kind === "change" ? (
          <p className={styles.tileChange} data-direction={change.direction}>
            {change.pct} <span className={styles.meta}>7D</span>
          </p>
        ) : (
          <p className={styles.tileChange} title={change.reason}>
            — <span className={styles.meta}>7D: {change.reason}</span>
          </p>
        )}

        <p className={styles.meta} data-testid="checked">
          {entry.checked_at ? <time dateTime={entry.checked_at}>{checkedAgo(entry.checked_at, now)}</time> : checkedAgo(null, now)}
        </p>

        <div className={`${styles.tileActions} ${watch.actions}`}>
          <WatchEditSheet
            entryId={entry.id}
            cardPrintId={entry.card_print_id}
            versionLabel={`${name}${label ? ` · ${label}` : ""}`}
            targetJpy={entry.target_jpy}
            buttonDescription={`Edit target for ${name}${label ? `, ${label}` : ""}`}
          />
        </div>
      </div>
    </li>
  );
}
