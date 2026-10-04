"use client";

import { AtlasMark } from "@/components/brand/AtlasMark";
import { InfoTip } from "@/components/ui/InfoTip";
import { MarketValueChart } from "@/components/ui/MarketValueChart";
import { MARKET_VALUE_WINDOWS, marketDate, marketJpy, marketNumber, marketPercent, marketWindowLabel, movementUnavailable, type MarketValue, type MarketValueMode, type MarketValueRelease, type MarketValueWindow } from "@/lib/marketValue";
import { releaseLabelEnglish } from "@/lib/releaseNames";
import styles from "./MarketValueHero.module.css";

export interface MarketValueHeroProps {
  data: MarketValue | null;
  busy: boolean;
  error: string | null;
  releases: MarketValueRelease[];
  releasesFailed: boolean;
  releaseProductId: number | null | "invalid";
  window: MarketValueWindow;
  mode: MarketValueMode;
  onScopeChange: (id: number | null) => void;
  onWindowChange: (window: MarketValueWindow) => void;
  onModeChange: (mode: MarketValueMode) => void;
  onRetry: () => void;
}

export function MarketValueHero(props: MarketValueHeroProps) {
  const { data, busy, error, releases, releasesFailed, releaseProductId, window, mode, onScopeChange, onWindowChange, onModeChange, onRetry } = props;
  const available = data?.movement.available === true && marketNumber(data.movement.pct) !== null;
  const unavailable = data ? movementUnavailable(data) : null;
  const scopeLabel = data?.scope_kind === "release"
    ? releaseLabelEnglish(data.release_code, data.release_name)
    : "All One Piece";
  const tracked = data?.tracked_value;
  const coverage = marketNumber(tracked?.physical_coverage_pct ?? null);
  const hasSelectedOption = releaseProductId === null || releases.some((release) => release.release_product_id === releaseProductId);
  const displayWindow = data?.movement.window ?? window;

  return (
    <section className={styles.hero} aria-labelledby="market-title" data-testid="market-value-hero">
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>One Piece card prices</p>
          <h1 id="market-title">How is the One Piece market doing?</h1>
          <p className={styles.subtitle}>See what is rising or falling across the Japanese card variants we track. Coverage is partial.</p>
        </div>
        <div className={styles.scopeControl}>
          <label htmlFor="market-scope">Choose a release</label>
          <select id="market-scope" value={releaseProductId ?? ""} onChange={(event) => onScopeChange(event.target.value === "" ? null : Number(event.target.value))}>
            <option value="">All One Piece</option>
            {!hasSelectedOption && <option value={releaseProductId ?? ""}>{data?.release_product_id === releaseProductId ? scopeLabel : releaseProductId === "invalid" ? "Invalid release selection" : "Selected release"}</option>}
            {releases.map((release) => <option key={release.release_product_id} value={release.release_product_id}>{releaseLabelEnglish(release.release_code, release.release_name)}</option>)}
          </select>
          {releasesFailed && <p className={styles.selectorNote} role="status">Release list unavailable. Overall Market is still available.</p>}
        </div>
      </header>

      <div className={styles.controls}>
        <div className={styles.modeControls}>
          <div className={styles.modeSwitch} role="group" aria-label="Chart mode">
            <button type="button" aria-pressed={mode === "performance"} onClick={() => onModeChange("performance")}>Comparable performance</button>
            <button type="button" aria-pressed={mode === "value"} onClick={() => onModeChange("value")}>Market Value</button>
          </div>
          <InfoTip className={styles.modeHelp} label="About chart modes" text={mode === "performance" ? "Coverage-neutral price movement across comparable cards." : "Partial JPY value of the cards Card Pirate currently prices. Coverage additions and removals can change this line independently of prices."} />
        </div>
        <div className={styles.windows} role="group" aria-label="Market window">
          {MARKET_VALUE_WINDOWS.map((token) => <button type="button" key={token} aria-pressed={window === token} onClick={() => onWindowChange(token)}>{marketWindowLabel(token)}</button>)}
        </div>
      </div>

      <div className={styles.settled} aria-busy={busy} data-testid="market-settled">
        <div className={styles.statusLine} role="status">{busy ? data ? "Updating view…" : "Loading market…" : ""}</div>
        {error ? (
          <div className={styles.error} role="alert">
            <p className={styles.eyebrow}>Market unavailable</p>
            <h2>{error}</h2>
            <p>Please try again or choose another market.</p>
            <button type="button" onClick={onRetry}>Try again</button>
          </div>
        ) : !data ? (
          <div className={styles.skeleton} aria-label="Loading Market view"><div /><div /><div /></div>
        ) : (
          <>
            <div className={styles.headline}>
              <div className={styles.headlineMain}>
                <h2>{data.scope_kind === "overall" ? "One Piece price movement" : scopeLabel}</h2>
                {available ? (
                  <p className={styles.movement} data-testid="market-movement"><span>{marketPercent(data.movement.pct)}</span><span className={styles.period}>{marketWindowLabel(displayWindow)}</span></p>
                ) : <p className={styles.unavailableHeadline} data-testid="market-movement-unavailable"><span className={styles.period}>{marketWindowLabel(displayWindow)}</span> Unavailable<span className={styles.selectorNote}>{unavailable?.detail}</span></p>}
                {data.scope_kind === "release" && !available && tracked && <p className={styles.sparseCoverage}>{tracked.priced_print_count.toLocaleString("en-US")} / {tracked.total_physical_print_count.toLocaleString("en-US")} card variants priced</p>}
              </div>
              <p className={styles.asOf}>Published <time dateTime={data.as_of}>{marketDate(data.as_of, true)}</time></p>
            </div>

            <div className={styles.chartFrame}>
              <h3 className={styles.chartTitle}>Price Movement</h3>
              <MarketValueChart series={data.series} mode={mode} />
              <div className={styles.chartFooter}>
                <div className={styles.watermark} data-testid="market-watermark">
                  <AtlasMark title={null} />
                  <div><strong>CARD PIRATE</strong><span>Japanese card prices · JPY</span></div>
                </div>
                <span className={styles.chartCaption}>{mode === "performance" ? "Comparable performance · %" : "Market Value · JPY"}</span>
              </div>
            </div>

            {tracked && <div className={styles.tracked} data-testid="market-tracked-value">
              <div>
                <p className={styles.trackedLabel}>{data.scope_kind === "release" && !available ? "Tracked so far" : "Tracked value"}<InfoTip label="About tracked value" text="Value of one copy of every physical version Card Pirate currently prices in this scope." /></p>
                <p className={styles.trackedNumber}>{marketJpy(tracked.value_jpy)}</p>
              </div>
              <div className={styles.coverage}>
                <p>{tracked.priced_print_count.toLocaleString("en-US")} of {tracked.total_physical_print_count.toLocaleString("en-US")} card variants priced<span>{coverage === null ? "Coverage unavailable" : `${coverage.toFixed(1)}% coverage`}</span></p>
                <p>{tracked.is_partial ? "A partial basket. Unpriced card variants are not valued at zero." : "One copy of each priced physical version."}</p>
              </div>
            </div>}
          </>
        )}
      </div>
    </section>
  );
}
