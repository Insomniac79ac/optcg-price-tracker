"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { resolveCardImageUrl } from "@/lib/cardImage";
import {
  fetchMarketValueMostValuable, fetchMarketValueMovers, marketDate, marketJpy,
  marketPercentagePoints, marketPercent, marketSignedJpy,
  type MarketValueMover, type MarketValueMoverOrder, type MarketValuePrint,
} from "@/lib/marketValue";
import styles from "./MarketValueDiscovery.module.css";

const MODES: { order: MarketValueMoverOrder; label: string }[] = [
  { order: "gainers", label: "Gainers" },
  { order: "losers", label: "Losers" },
  { order: "impact", label: "Market impact" },
];

/** Each section owns its request and retry. Keep settled payloads intact while
 * refreshing, and ignore successes AND failures from abandoned selections. */
function useRanking<T>(selection: string, request: () => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const key = `${selection}:${attempt}`;
  const [settled, setSettled] = useState<{ key: string; data: T | null; failed: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    request().then((data) => {
      if (!cancelled) setSettled({ key, data, failed: false });
    }).catch(() => {
      if (!cancelled) setSettled({ key, data: null, failed: true });
    });
    return () => { cancelled = true; };
  }, [key, request]);
  const busy = settled?.key !== key;
  return { data: settled?.data ?? null, busy, failed: !busy && settled?.failed === true, retry: () => setAttempt((n) => n + 1) };
}

function PrintArtwork({ item }: { item: MarketValuePrint }) {
  return <CardImageFrame
    key={`${item.card_print_id}:${item.display_image?.url ?? ""}`}
    imageUrl={resolveCardImageUrl(item.display_image?.url ?? null)}
    alt={item.name}
    cardCode={item.card_code}
    setCode={item.release_code}
    rarity={item.rarity}
    geometry={item.display_image?.url ? item.display_image.geometry : null}
    size="full"
    padded
  />;
}

function PrintIdentity({ item }: { item: MarketValuePrint }) {
  return <>
    <h3 className={styles.cardName}>{item.name}</h3>
    <p className={styles.identity}>{item.card_code}{item.release_code && <span>{item.release_code}</span>}</p>
  </>;
}

function LocalError({ children, retry }: { children: React.ReactNode; retry: () => void }) {
  return <div className={styles.empty} role="alert"><p>{children}</p><button type="button" onClick={retry}>Try again</button></div>;
}

function MoverCard({ item, order }: { item: MarketValueMover; order: MarketValueMoverOrder }) {
  const impact = order === "impact";
  return <li>
    <Link href={`/prints/${item.card_print_id}`} className={styles.card}>
      <PrintArtwork item={item} />
      <PrintIdentity item={item} />
      <p className={styles.metric} data-direction={item.direction} data-testid="mover-primary">
        <span>{impact ? marketSignedJpy(item.delta_jpy) : marketPercent(item.move_pct)}</span>
        <span className={styles.direction}>{item.direction === "up" ? "↗ Up" : item.direction === "down" ? "↘ Down" : "→ Flat"}</span>
      </p>
      {impact ? <>
        <p className={styles.support}>Impact {marketPercentagePoints(item.percentage_point_contribution)}</p>
        <p className={styles.context}>Card price {marketPercent(item.move_pct)}</p>
      </> : <>
        <p className={styles.support}>{marketJpy(item.prior_value_jpy)} → {marketJpy(item.current_value_jpy)}</p>
        <p className={styles.context}>Basket change {marketSignedJpy(item.delta_jpy)}</p>
      </>}
    </Link>
  </li>;
}

export function MarketValueMoversSection({ releaseProductId }: { releaseProductId: number | null }) {
  const [order, setOrder] = useState<MarketValueMoverOrder>("gainers");
  const request = useCallback(() => fetchMarketValueMovers(releaseProductId, order), [releaseProductId, order]);
  const { data, busy, failed, retry } = useRanking(`${releaseProductId ?? "overall"}:${order}`, request);
  // Metrics and dates belong to the settled payload, even when a newer tab is loading.
  const displayOrder = data?.order ?? order;

  return <section className={styles.section} aria-labelledby="market-movers-title" data-testid="market-value-movers">
    <header className={styles.header}>
      <div><h2 id="market-movers-title">Market movers</h2><p>What changed in the latest published market step.</p></div>
      <div className={styles.modes} role="group" aria-label="Mover mode">
        {MODES.map((mode) => <button type="button" key={mode.order} aria-pressed={order === mode.order} onClick={() => setOrder(mode.order)}>{mode.label}</button>)}
      </div>
    </header>
    <div className={styles.settled} aria-busy={busy} data-testid="movers-settled">
      <p className={styles.status} role="status">{busy ? data ? `Updating… Showing previous ${MODES.find((mode) => mode.order === data.order)?.label.toLowerCase()} for ${data.release_code ?? "All One Piece"}.` : "Loading market movers…" : ""}</p>
      {failed ? <LocalError retry={retry}>Market movers could not be loaded.</LocalError> : data && <>
        <div className={styles.sectionContext}>
          {displayOrder === "impact" && <p>Largest contributors to the latest basket move.</p>}
          {data.step_date && <p className={styles.date}>{data.step_date < data.scope_as_of
            ? <>Latest published movement: <time dateTime={data.step_date}>{marketDate(data.step_date)}</time></>
            : <>Movement: {data.prior_date && <><time dateTime={data.prior_date}>{marketDate(data.prior_date)}</time> → </>}<time dateTime={data.step_date}>{marketDate(data.step_date)}</time></>}</p>}
        </div>
        {!data.available ? <div className={styles.empty}><h3>No published price movement yet</h3><p>Price coverage is still being built for {data.scope_kind === "release" ? "this release" : "this market"}.</p></div>
          : data.total_ranked === 0 ? <div className={styles.empty}><p>{displayOrder === "impact" || data.panel.basket_delta_jpy === 0
            ? "No cards moved in the latest published step."
            : `No ${displayOrder} in the latest published step.`}</p></div>
          : <ul className={styles.movers}>{data.movers.map((item) => <MoverCard key={item.card_print_id} item={item} order={displayOrder} />)}</ul>}
      </>}
    </div>
  </section>;
}

export function MarketValueMostValuableSection({ releaseProductId, releaseCode }: { releaseProductId: number | null; releaseCode: string | null }) {
  const request = useCallback(() => fetchMarketValueMostValuable(releaseProductId), [releaseProductId]);
  const { data, busy, failed, retry } = useRanking(`${releaseProductId ?? "overall"}`, request);
  const code = releaseProductId === null ? null : releaseCode ?? (data?.release_product_id === releaseProductId ? data.release_code : null);
  const heading = code ? `Most valuable in ${code}` : "Most valuable cards";
  const browseUrl = releaseProductId === null ? "/cards" : `/cards?release_product_id=${releaseProductId}`;

  return <section className={styles.section} aria-labelledby="market-valuable-title" data-testid="market-value-most-valuable">
    <header className={styles.header}>
      <div><h2 id="market-valuable-title">{heading}</h2></div>
      <Link className={styles.browse} href={browseUrl}>Browse all cards →</Link>
    </header>
    <div className={styles.settled} aria-busy={busy} data-testid="valuable-settled">
      <p className={styles.status} role="status">{busy ? data ? `Updating… Showing previous prices for ${data.release_code ?? "All One Piece"}.` : "Loading most valuable cards…" : ""}</p>
      {failed ? <LocalError retry={retry}>Most valuable cards could not be loaded.</LocalError> : data && <>
        <p className={styles.date}>Prices through <time dateTime={data.as_of}>{marketDate(data.as_of)}</time></p>
        {data.total_eligible === 0 ? <div className={styles.empty}><p>No priced cards yet for this scope.</p></div>
          : <ul className={styles.valuable}>{data.items.map((item) => <li key={item.card_print_id}>
            <Link href={`/prints/${item.card_print_id}`} className={styles.card}>
              <PrintArtwork item={item} />
              <PrintIdentity item={item} />
              <p className={styles.value}>{marketJpy(item.value_jpy)}</p>
              <p className={styles.context}>Tracked value</p>
            </Link>
          </li>)}</ul>}
      </>}
    </div>
  </section>;
}
