"use client";

import { useState } from "react";
import { marketDate, marketJpy, marketNumber, marketPercent, type MarketValueMovementSummary, type MarketValueRelease } from "@/lib/marketValue";
import { releaseMovementReason } from "@/lib/marketValueComparison";
import { releaseDisplayNameEnglish, releaseLabelEnglish } from "@/lib/releaseNames";
import styles from "./MarketValueReleases.module.css";

function Movement({ data, window }: { data: MarketValueMovementSummary; window: string }) {
  const available = data.available && marketNumber(data.pct) !== null;
  return <span className={styles.cell}>
    <span className={styles.mobileLabel}>{window} </span>
    <span>{available ? marketPercent(data.pct) : "—"}</span>
    {!available && <small>{releaseMovementReason(data.reason)}</small>}
  </span>;
}

export function MarketValueReleaseMarket({ releases, loading, failed, onScopeChange }: {
  releases: MarketValueRelease[];
  loading: boolean;
  failed: boolean;
  onScopeChange: (id: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(12);
  // Filter, never sort: both the initial page and searches retain API chronology.
  const matches = releases.filter((release) => releaseLabelEnglish(release.release_code, release.release_name).toLowerCase().includes(search.trim().toLowerCase()));
  const dates = [...new Set(releases.map((release) => release.as_of))];
  return <section className={`${styles.section} ${styles.releaseMarket}`} aria-labelledby="release-market-title" data-testid="release-market">
    <header className={styles.header}>
      <div><h2 id="release-market-title">Release market</h2><p>Tracked value and price coverage across One Piece releases.</p></div>
      <label className={styles.search}>Search releases<input type="search" value={search} placeholder="Code or English name" onChange={(event) => { setSearch(event.target.value); setLimit(12); }} /></label>
    </header>
    {loading ? <p className={styles.notice} role="status">Loading release markets…</p>
      : failed ? <p className={styles.notice}>Release markets could not be loaded.</p>
      : <>
        {dates.length === 1 && <p className={styles.asOf}>Prices through <time dateTime={dates[0]}>{marketDate(dates[0], true)}</time></p>}
        <div className={styles.tableHeading} aria-hidden="true"><span>Release</span><span>Tracked value</span><span>Coverage</span><span>7D</span><span>30D</span></div>
        <ul className={styles.releaseList} aria-label="Release markets">
          {matches.slice(0, limit).map((release) => <li key={release.release_product_id}>
            <button type="button" className={styles.releaseRow} aria-label={`View ${releaseLabelEnglish(release.release_code, release.release_name)} Market`} onClick={() => onScopeChange(release.release_product_id)}>
              <span className={styles.releaseIdentity}><strong>{release.release_code}</strong><span>{releaseDisplayNameEnglish(release.release_code)}</span></span>
              <span className={styles.cell}><span className={styles.mobileLabel}>Tracked </span><span>{marketJpy(release.tracked_value.value_jpy)}</span>{release.tracked_value.value_jpy !== null && release.tracked_value.is_partial && <small>Tracked so far</small>}{dates.length > 1 && <small>Through {marketDate(release.as_of)}</small>}</span>
              <span className={styles.cell}><span>{release.tracked_value.priced_print_count.toLocaleString("en-US")} / {release.tracked_value.total_physical_print_count.toLocaleString("en-US")} priced</span>{release.tracked_value.physical_coverage_pct !== null && <small>{marketPercent(release.tracked_value.physical_coverage_pct, false)}</small>}</span>
              <Movement data={release.seven_day} window="7D" />
              <Movement data={release.thirty_day} window="30D" />
              <span className={styles.rowHint}>Tap for Market view →</span>
            </button>
          </li>)}
        </ul>
        {!matches.length && <p className={styles.notice}>{releases.length ? "No releases match your search." : "No release markets yet."}</p>}
        {matches.length > limit && <button type="button" className={styles.showMore} onClick={() => setLimit((value) => value + 12)}>Show more <span>({matches.length - limit} remaining)</span></button>}
      </>}
  </section>;
}
