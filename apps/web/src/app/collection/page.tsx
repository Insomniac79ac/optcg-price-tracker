import type { Metadata } from "next";
import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { CollectionEditSheet } from "@/components/collection/CollectionEditSheet";
import { CollectionHistoryChart } from "@/components/collection/CollectionHistoryChart";
import styles from "@/components/collection/Collection.module.css";
import { AccountChapter, AccountHero, accountSurfaceStyles as surface } from "@/components/ui/AccountSurface";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { auth } from "@/lib/auth";
import {
  COLLECTION_WINDOWS,
  WINDOW_LABEL,
  cardName,
  coverageLine,
  direction,
  parseCollectionWindow,
  shortDate,
  signedPct,
  signedYen,
  tileChange,
  unavailableReason,
  yen,
  type CollectionEntry,
  type CollectionValue,
  type CollectionWindow,
  type Mover,
  type ReleaseShare,
} from "@/lib/collection";
import { loadCollectionPage } from "@/lib/collectionServer";
import { collectorIdentity } from "@/lib/collectorApi";
import { toPrintUiModel, type PrintUiModel } from "@/lib/prints";
import { readPrint } from "@/lib/publicServer";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Your collection" };

const LINK = "inline-flex min-h-11 items-center rounded-control border border-[#3e696a] px-4 text-sm font-medium text-[#8dc9c4] transition-colors hover:border-accent-teal hover:text-text-primary";

/** The signed-in collector's collection (Collector v1 S7, PLAN §E2), read
 * server-side from the v1 accounts API. Order: value with its date and
 * coverage, 7D/30D/ALL, history, what moved it, by set, the cards, what you
 * paid, then the cards that still need a version.
 *
 * Every number is the API's: unpriced cards read "No price yet" and stay out
 * of the total, and a window without a publishable change shows "—" with the
 * reason, never 0%. src/proxy.ts already sends anyone who is not a collector
 * to /sign-in; the session is checked again here. */
export default async function CollectionPage({ searchParams }: { searchParams: Promise<{ window?: string | string[] }> }) {
  const identity = collectorIdentity(await auth());
  const window = parseCollectionWindow((await searchParams).window);
  if (!identity) {
    return (
      <Frame>
        <AccountHero>
          <p className={surface.kicker}>Your collection</p>
          <h1 className={surface.title}>Sign in to see your collection</h1>
          <div className={surface.links}>
            <Link href="/sign-in?callbackUrl=%2Fcollection" className={LINK}>Sign in</Link>
          </div>
        </AccountHero>
      </Frame>
    );
  }

  const data = await loadCollectionPage(identity);
  if (data.state !== "ok") {
    return (
      <Frame>
        <AccountHero>
          <p className={surface.kicker}>Your collection</p>
          <h1 className={surface.title}>{data.state === "disabled" ? "Collections aren’t switched on yet" : "We couldn’t load your collection"}</h1>
          <p className={surface.supporting}>
            {data.state === "disabled"
              ? "Card prices and the market are still open to browse."
              : "Nothing has changed in it. Please reload the page in a moment."}
          </p>
          <div className={surface.links}>
            {data.state === "error" && <Link href="/collection" className={LINK}>Reload</Link>}
            <Link href="/cards" className={LINK}>Browse cards</Link>
          </div>
        </AccountHero>
      </Frame>
    );
  }

  const { collection, values } = data;
  const value = values[window];
  if (collection.entries.length === 0) return <EmptyCollection />;

  const exact = collection.entries.filter((entry) => entry.resolution === "exact" && entry.card_print_id !== null);
  const unresolved = collection.entries.filter((entry) => entry.resolution !== "exact" || entry.card_print_id === null);
  const prints = await loadPrints(exact.map((entry) => entry.card_print_id as number));
  const summary = collection.summary;
  const asOf = shortDate(collection.as_of);
  const entryByPrint = new Map(exact.map((entry) => [entry.card_print_id as number, entry]));
  const sorted = [...exact].sort((a, b) => (b.value_jpy ?? -1) - (a.value_jpy ?? -1) || a.id - b.id);
  const hasPaid = (value?.paid.cards_with_paid ?? 0) > 0;
  let chapter = 0;
  const next = () => String(++chapter).padStart(2, "0");

  return (
    <Frame>
      <AccountHero aside={<WindowChips window={window} values={values} />}>
        <p className={surface.kicker}>Your collection</p>
        <h1 className={`${surface.title} ${styles.value}`} data-testid="collection-value">
          {summary.value_jpy !== null ? yen(summary.value_jpy) : "No prices yet"}
        </h1>
        <p className={styles.asOf}>
          {asOf ? `Prices as of ${asOf}` : "No daily price check yet"}
          <span aria-hidden="true"> · </span>
          <span data-testid="collection-coverage">{coverageLine(summary)}</span>
        </p>
        {summary.priced_cards < summary.total_cards && (
          <p className={styles.coverageNote}>
            Cards without a price yet are left out of the total, never counted as ¥0.
          </p>
        )}
      </AccountHero>

      <section aria-labelledby="history" className={styles.section}>
        <AccountChapter id="history" number={next()} title="Value over time" />
        <div className={styles.panel}>
          <CollectionHistoryChart
            recorded={value?.history.points ?? []}
            preview={value?.preview.points ?? []}
            previewLabel={value?.preview.label ?? "Preview"}
          />
        </div>
      </section>

      {value && (value.movers.up.length > 0 || value.movers.down.length > 0 || !value.movers.available) && (
        <section aria-labelledby="moved" className={styles.section}>
          <AccountChapter id="moved" number={next()} title="What moved your collection">
            {value.movers.available && value.movers.from_date && value.movers.to_date
              ? `${shortDate(value.movers.from_date)} to ${shortDate(value.movers.to_date)}, by yen impact`
              : undefined}
          </AccountChapter>
          {value.movers.available ? (
            <div className={styles.moverColumns}>
              <MoverList title="Up" movers={value.movers.up} entries={entryByPrint} prints={prints} />
              <MoverList title="Down" movers={value.movers.down} entries={entryByPrint} prints={prints} />
            </div>
          ) : (
            <p className={styles.unavailable}>— {unavailableReason(value.movers)}</p>
          )}
        </section>
      )}

      {value && value.by_release.length > 0 && (
        <section aria-labelledby="by-set" className={styles.section}>
          <AccountChapter id="by-set" number={next()} title="By set" />
          <ul className={styles.sets}>
            {value.by_release.map((share) => (
              <SetRow key={share.release_product_id ?? "none"} share={share} window={window} />
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="cards" className={styles.section}>
        <AccountChapter id="cards" number={next()} title="Your cards">
          {`${summary.total_cards} ${summary.total_cards === 1 ? "card" : "cards"}, ${summary.total_entries} ${summary.total_entries === 1 ? "version" : "versions"}`}
        </AccountChapter>
        <ul className={styles.grid} data-testid="collection-grid">
          {sorted.map((entry) => (
            <CardTile key={entry.id} entry={entry} print={prints.get(entry.card_print_id as number) ?? null} value={value} window={window} />
          ))}
        </ul>
      </section>

      {value && hasPaid && (
        <section aria-labelledby="paid" className={styles.section}>
          <AccountChapter id="paid" number={next()} title="What you paid" />
          <PaidPanel value={value} />
        </section>
      )}

      {unresolved.length > 0 && (
        <section aria-labelledby="needs-version" className={styles.section}>
          <AccountChapter id="needs-version" number={next()} title="Needs a version">
            These came from your old collection and match more than one version, so they have no price yet.
          </AccountChapter>
          <ul className={styles.needs}>
            {unresolved.map((entry) => (
              <NeedsVersionRow key={entry.id} entry={entry} />
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

function versionLabel(entry: CollectionEntry, print: PrintUiModel | null): string {
  const code = print?.cardCode ?? entry.print?.card_code;
  const release = print?.releaseCode ?? entry.print?.release_code;
  return [code, print?.printingType?.label, release].filter(Boolean).join(" · ");
}

function EmptyCollection() {
  return (
    <Frame>
      <AccountHero>
        <p className={surface.kicker}>Your collection</p>
        <h1 className={surface.title}>Your collection is empty</h1>
        <p className={surface.supporting}>
          Find a card, open the exact version you have, and choose “Add to collection”. Its price,
          what you paid and how it moves will show up here.
        </p>
        <div className={surface.links}>
          <Link href="/cards" className={styles.primaryLink}>Find a card</Link>
        </div>
      </AccountHero>
    </Frame>
  );
}

function WindowChips({ window, values }: { window: CollectionWindow; values: Record<CollectionWindow, CollectionValue | null> }) {
  const selected = values[window];
  return (
    <div className={styles.chipsBlock}>
      <nav aria-label="Change over time" className={styles.chips}>
        {COLLECTION_WINDOWS.map((w) => {
          const change = values[w]?.history.change ?? null;
          const pct = change?.available ? signedPct(change.change_pct) : null;
          const reason = pct === null ? unavailableReason(change) : undefined;
          return (
            <Link
              key={w}
              href={w === "7d" ? "/collection" : `/collection?window=${w}`}
              scroll={false}
              aria-current={w === window ? "page" : undefined}
              className={styles.chip}
              title={reason}
              data-window={w}
            >
              <span className={styles.chipLabel}>{WINDOW_LABEL[w]}</span>
              <span className={styles.chipValue} data-direction={pct ? direction(change?.change_pct) : undefined}>
                {pct ?? "—"}
              </span>
            </Link>
          );
        })}
      </nav>
      {(() => {
        const change = selected?.history.change ?? null;
        if (change?.available && signedPct(change.change_pct) !== null) {
          return (
            <p className={styles.chipNote}>
              {WINDOW_LABEL[window]} change in your recorded collection, {shortDate(change.from_date)} to {shortDate(change.to_date)}.
            </p>
          );
        }
        return <p className={styles.chipNote} data-testid="window-reason">{WINDOW_LABEL[window]}: — {unavailableReason(change)}.</p>;
      })()}
    </div>
  );
}

function MoverList({
  title,
  movers,
  entries,
  prints,
}: {
  title: "Up" | "Down";
  movers: Mover[];
  entries: Map<number, CollectionEntry>;
  prints: Map<number, PrintUiModel>;
}) {
  return (
    <div className={styles.panel}>
      <h3 className={styles.panelHeading}>{title}</h3>
      {movers.length === 0 ? (
        <p className={styles.quiet}>{title === "Up" ? "Nothing rose in this window." : "Nothing fell in this window."}</p>
      ) : (
        <ol className={styles.movers}>
          {movers.map((mover) => {
            const entry = entries.get(mover.card_print_id) ?? null;
            const print = prints.get(mover.card_print_id) ?? null;
            const name = print?.displayName ?? cardName(entry?.print ?? null);
            return (
              <li key={mover.card_print_id} className={styles.mover}>
                <span className={styles.moverName}>
                  <Link href={`/prints/${mover.card_print_id}`}>
                    {name}
                    {print?.printingType && <span className={styles.moverVersion}> · {print.printingType.label}</span>}
                  </Link>
                  <span className={styles.meta}>
                    {entry ? versionLabel(entry, print) : print?.cardCode}
                    {mover.units > 1 ? ` · ×${mover.units}` : ""}
                  </span>
                </span>
                <span className={styles.moverFigures} data-direction={direction(mover.delta_jpy)}>
                  <span>{signedYen(mover.delta_jpy)}</span>
                  <span className={styles.meta}>{signedPct(mover.change_pct) ?? "—"}</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function SetRow({ share, window }: { share: ReleaseShare; window: CollectionWindow }) {
  const pct = share.change.available ? signedPct(share.change.change_pct) : null;
  const sharePct = share.share_pct !== null ? Number(share.share_pct) : null;
  return (
    <li className={styles.setRow}>
      <div className={styles.setHead}>
        <div className={styles.setName}>
          <span>{share.release_name ?? (share.release_product_id === null ? "Needs a version" : "Unknown set")}</span>
          {share.release_code && <span className={styles.code}>{share.release_code}</span>}
        </div>
        <span className={styles.setValue}>{share.value_jpy !== null ? yen(share.value_jpy) : "No price yet"}</span>
      </div>
      <div className={styles.shareBar} aria-hidden="true">
        <span style={{ width: `${sharePct !== null && Number.isFinite(sharePct) ? Math.max(0, Math.min(100, sharePct)) : 0}%` }} />
      </div>
      <div className={styles.setFoot}>
        <span className={styles.meta}>
          Priced: {share.priced_cards} of {share.total_cards}
          {sharePct !== null && Number.isFinite(sharePct) ? ` · ${Math.round(sharePct)}% of your collection` : ""}
        </span>
        <span className={styles.setChange} data-direction={pct ? direction(share.change.change_pct) : undefined} title={pct ? undefined : unavailableReason(share.change)}>
          {pct ? `${pct} ${WINDOW_LABEL[window]}` : `— ${WINDOW_LABEL[window]}: ${share.value_jpy === null ? "No price yet" : unavailableReason(share.change)}`}
        </span>
      </div>
    </li>
  );
}

function CardTile({ entry, print, value, window }: { entry: CollectionEntry; print: PrintUiModel | null; value: CollectionValue | null; window: CollectionWindow }) {
  const name = print?.displayName ?? cardName(entry.print);
  const code = print?.cardCode ?? entry.print?.card_code ?? "";
  const label = versionLabel(entry, print);
  const change = tileChange(value, entry);
  const href = `/prints/${entry.card_print_id}`;
  return (
    <li className={styles.tile} data-testid="collection-card">
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
        {entry.quantity > 1 && <span className={styles.quantity}>×{entry.quantity}</span>}
      </Link>
      <div className={styles.tileBody}>
        <h3 className={styles.tileName}>
          <Link href={href}>{name}</Link>
        </h3>
        <p className={styles.meta}>{label}</p>
        <p className={styles.tileValue}>
          {entry.value_jpy !== null ? (
            <>
              <span>{yen(entry.value_jpy)}</span>
              {entry.quantity > 1 && entry.value_per_card_jpy !== null && <span className={styles.meta}> · {yen(entry.value_per_card_jpy)} each</span>}
            </>
          ) : (
            <span className={styles.noPrice}>No price yet</span>
          )}
        </p>
        {change.kind === "change" ? (
          <p className={styles.tileChange} data-direction={change.direction}>
            {change.pct} <span className={styles.meta}>{WINDOW_LABEL[window]}</span>
          </p>
        ) : (
          entry.value_status === "priced" && (
            <p className={styles.tileChange} title={change.reason}>
              — <span className={styles.meta}>{WINDOW_LABEL[window]}: {change.reason}</span>
            </p>
          )
        )}
        <div className={styles.tileActions}>
          <CollectionEditSheet
            entryId={entry.id}
            cardPrintId={entry.card_print_id}
            versionLabel={`${name}${label ? ` · ${label}` : ""}`}
            quantity={entry.quantity}
            paidJpyPerCard={entry.paid_jpy_per_card}
            acquiredOn={entry.acquired_on}
            buttonDescription={`Edit ${name}${label ? `, ${label}` : ""}`}
          />
        </div>
      </div>
    </li>
  );
}

function PaidPanel({ value }: { value: CollectionValue }) {
  const { paid } = value;
  const pct = signedPct(paid.change_pct);
  const left = paid.cards_with_paid - paid.cards_compared;
  return (
    <div className={`${styles.panel} ${styles.paid}`}>
      {paid.paid_jpy !== null && paid.priced_today_jpy !== null ? (
        <p className={styles.paidLine}>
          You paid <strong>{yen(paid.paid_jpy)}</strong> for {paid.cards_compared} {paid.cards_compared === 1 ? "card" : "cards"}. Priced today:{" "}
          <strong>{yen(paid.priced_today_jpy)}</strong>
          {pct && <span className={styles.paidPct} data-direction={direction(paid.change_pct)}> ({pct})</span>}.
        </p>
      ) : (
        <p className={styles.paidLine}>None of the cards you entered a price for has a price today yet.</p>
      )}
      <p className={styles.meta}>
        {paid.cards_with_paid} of {paid.total_cards} cards have what you paid.
        {left > 0 ? ` ${left} of them ${left === 1 ? "has" : "have"} no price today and ${left === 1 ? "is" : "are"} left out.` : ""}
      </p>
    </div>
  );
}

function NeedsVersionRow({ entry }: { entry: CollectionEntry }) {
  return (
    <li className={styles.needsRow}>
      <div className="min-w-0">
        <p className={styles.needsName}>{entry.print ? cardName(entry.print) : "A card from your old collection"}</p>
        <p className={styles.meta}>
          ×{entry.quantity}
          {entry.paid_jpy_per_card !== null ? ` · you paid ${yen(entry.paid_jpy_per_card)} each` : ""}
          {entry.note ? ` · ${entry.note}` : ""}
        </p>
      </div>
      <div className={styles.needsActions}>
        <Link href="/cards" className={LINK}>Find the version</Link>
        <CollectionEditSheet
          entryId={entry.id}
          cardPrintId={null}
          versionLabel={entry.note ?? "A card from your old collection"}
          quantity={entry.quantity}
          paidJpyPerCard={entry.paid_jpy_per_card}
          acquiredOn={entry.acquired_on}
          buttonDescription="Edit this card from your old collection"
        />
      </div>
    </li>
  );
}
