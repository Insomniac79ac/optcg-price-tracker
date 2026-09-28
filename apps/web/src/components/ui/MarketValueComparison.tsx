"use client";

import { useEffect, useRef, useState } from "react";
import { AtlasMark } from "@/components/brand/AtlasMark";
import { CollectorMultiSelect } from "@/components/ui/CollectorMultiSelect";
import { COMPARISON_COLORS, MarketValueComparisonChart, type ComparisonLine } from "@/components/ui/MarketValueComparisonChart";
import { fetchMarketValue, type MarketValue, type MarketValueRelease } from "@/lib/marketValue";
import { releaseLabelEnglish } from "@/lib/releaseNames";
import heroStyles from "./MarketValueHero.module.css";
import styles from "./MarketValueReleases.module.css";

interface Entry {
  release: MarketValueRelease;
  slot: number;
  token: number;
  status: "loading" | "ready" | "error";
  data: MarketValue | null;
}

export function MarketValueComparison({ releases, loading, failed }: {
  releases: MarketValueRelease[];
  loading: boolean;
  failed: boolean;
}) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const sequence = useRef(0);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  // Only explicit additions/retries fetch. Active Market scope and census
  // rerenders cannot re-request comparison series. Tokens also protect remove
  // then re-add of the SAME release while an older request is still running.
  function request(entry: Entry) {
    const finish = (data: MarketValue | null) => {
      if (!mounted.current) return;
      setEntries((current) => current.some((item) => item.token === entry.token)
        ? current.map((item) => item.token === entry.token ? { ...item, status: data ? "ready" : "error", data } : item)
        : current);
    };
    fetchMarketValue(entry.release.release_product_id, "7d").then((data) => {
      finish(data.scope_kind === "release" && data.release_product_id === entry.release.release_product_id ? data : null);
    }).catch(() => finish(null));
  }

  function select(ids: string[]) {
    const selected = ids.map((id) => releases.find((release) => String(release.release_product_id) === id))
      .filter((release): release is MarketValueRelease => Boolean(release?.seven_day.available)).slice(0, 4);
    const next = entries.filter((entry) => selected.some((release) => release.release_product_id === entry.release.release_product_id));
    const added: Entry[] = [];
    for (const release of selected) {
      if (next.some((entry) => entry.release.release_product_id === release.release_product_id)) continue;
      const slot = [0, 1, 2, 3].find((index) => !next.some((entry) => entry.slot === index))!;
      const entry: Entry = { release, slot, token: ++sequence.current, status: "loading", data: null };
      next.push(entry);
      added.push(entry);
    }
    setEntries(next);
    added.forEach(request);
  }

  function retry(entry: Entry) {
    const next: Entry = { ...entry, token: ++sequence.current, status: "loading", data: null };
    setEntries((current) => current.map((item) => item.token === entry.token ? next : item));
    request(next);
  }

  const selectedIds = entries.map((entry) => String(entry.release.release_product_id));
  const lines: ComparisonLine[] = entries.flatMap((entry) => entry.status === "ready" && entry.data ? [{
    id: entry.release.release_product_id, code: entry.release.release_code,
    label: releaseLabelEnglish(entry.release.release_code, entry.release.release_name), slot: entry.slot, data: entry.data,
  }] : []);
  const busy = entries.some((entry) => entry.status === "loading");

  return <section className={styles.section} aria-labelledby="compare-releases-title" data-testid="market-value-comparison">
    <header className={styles.header}>
      <div><h2 id="compare-releases-title">Compare releases</h2><p>Compare price movement across releases.</p></div>
      <span className={styles.period}>7D performance</span>
    </header>
    {failed ? <p className={styles.notice}>Release list unavailable. Comparison will be available when the list returns.</p>
      : loading ? <p className={styles.notice} role="status">Loading releases…</p>
      : <div className={styles.picker}>
        <CollectorMultiSelect label="Compare releases" emptyLabel="Select releases to compare" options={releases.map((release) => String(release.release_product_id))} selected={selectedIds} onChange={select} maxSelected={4}
          optionLabel={(id) => { const release = releases.find((item) => String(item.release_product_id) === id); return releaseLabelEnglish(release?.release_code, release?.release_name); }}
          optionDisabledReason={(id) => releases.find((release) => String(release.release_product_id) === id)?.seven_day.available ? null : "Price coverage in progress"} />
      </div>}
    {entries.length > 0 && <ul className={styles.legend} aria-label="Comparison legend">
      {entries.map((entry) => <li key={entry.release.release_product_id}>
        <span className={styles.swatch} style={{ backgroundColor: COMPARISON_COLORS[entry.slot] }} aria-hidden="true" />
        <span>{entry.release.release_code}</span>
        {entry.status === "loading" && <small>Loading…</small>}
        <button type="button" aria-label={`Remove ${entry.release.release_code}`} onClick={() => select(selectedIds.filter((id) => id !== String(entry.release.release_product_id)))}>×</button>
      </li>)}
    </ul>}
    {entries.filter((entry) => entry.status === "error").map((entry) => <p key={entry.release.release_product_id} className={styles.notice} role="status">
      {entry.release.release_code} could not be loaded. <button type="button" onClick={() => retry(entry)} aria-label={`Retry ${entry.release.release_code}`}>Retry</button>
    </p>)}
    <div aria-busy={busy} data-testid="comparison-settled">
      {!entries.length ? <div className={styles.empty}><p>Choose up to 4 releases to compare their 7D price movement.</p></div>
        : lines.length > 0 ? <div className={styles.visual}>
          <MarketValueComparisonChart lines={lines} />
          <div className={heroStyles.chartFooter}>
            <div className={heroStyles.watermark} data-testid="comparison-watermark"><AtlasMark title={null} /><div><strong>CARDPIRATE ATLAS</strong><span>cardpirateatlas.com</span></div></div>
            <span className={heroStyles.chartCaption}>7D price performance · %</span>
          </div>
        </div>
          : busy ? <div className={styles.empty} role="status"><p>Loading selected releases…</p></div> : null}
    </div>
  </section>;
}
