"use client";
import Link from "next/link";
import { usePublicResource } from "@/hooks/usePublicResource";
import { fetchMarketValueReleases, marketDate, marketJpy, marketPercent, marketScopeUrl, type MarketValueReleases } from "@/lib/marketValue";
import { homeSetMovers } from "@/lib/homeSetMovers";
import { releaseLabelEnglish, releaseDisplayNameEnglish } from "@/lib/releaseNames";
import { AtlasSectionIntro } from "./AtlasPrimitives";
import styles from "./HomeSetMovers.module.css";

export function HomeSetMovers({ initialData = null }: { initialData?: MarketValueReleases | null }) {
  const resource = usePublicResource(fetchMarketValueReleases, initialData);
  const sets = homeSetMovers(resource.data?.items ?? []);
  return <section aria-labelledby="home-sets" className={styles.section}>
    <div data-atlas-chapter><AtlasSectionIntro id="home-sets" number="03" title="Sets on the Move" description="See which One Piece sets are gaining or falling the most." /></div>
    <p className={styles.explanation}>Largest comparable 7-day moves, up or down. Coverage is partial.</p>
    {resource.status === "loading" && <p role="status" aria-label="Loading set movement">Loading set movement…</p>}
    {resource.status === "error" && <p role="status">Set movement could not be loaded. <button onClick={resource.retry}>Retry sets</button></p>}
    {resource.status === "ready" && !sets.length && <p>No sets have enough comparable history for a 7-day move yet.</p>}
    <ul className={styles.grid}>{sets.map((set) => <li key={set.release_product_id}>
      <Link href={marketScopeUrl(set.release_product_id)} prefetch={false}>
        <span className={styles.code}>{set.release_code || "Special release"}</span>
        <h3>{set.release_code ? releaseDisplayNameEnglish(set.release_code) : releaseLabelEnglish(null, set.release_name)}</h3>
        <strong className={styles.movement}>{marketPercent(set.seven_day.pct)} <small>7D</small></strong>
        <span className={styles.value}>Tracked Market Value <b>{marketJpy(set.tracked_value.value_jpy)}</b></span>
        <span className={styles.coverage}>{set.tracked_value.priced_print_count.toLocaleString("en-US")} of {set.tracked_value.total_physical_print_count.toLocaleString("en-US")} card variants priced{set.tracked_value.is_partial ? " · Partial coverage" : ""}</span>
        <time dateTime={set.as_of}>Published {marketDate(set.as_of, true)}</time>
        <span className={styles.cta}>See set prices →</span>
      </Link>
    </li>)}</ul>
    <Link href="/cards" className={styles.browse}>Browse by release →</Link>
  </section>;
}
