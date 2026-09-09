"use client";

import { formatDate, formatJpy } from "@/lib/format";
import {
  changeUnavailableCopy,
  formatSignedJpy,
  formatSignedPct,
  type PrintAnalytics,
  type PrintSeriesStats,
} from "@/lib/printAnalytics";
import {
  seriesInstrumentLabel,
  seriesPlatformLabel,
  type PrintSeries,
} from "@/lib/printSeries";

/** How each drawn series behaved across the window the chart is showing.
 *
 * EVERY NUMBER HERE IS THE SERVER'S, AND THE BROWSER COMPUTES NONE OF THEM.
 * The start, the current, the low, the high, the day count, the absolute move
 * and the percentage all arrive decided in `series_stats`; this component
 * chooses where they sit and formats them, and derives nothing from anything
 * else. That is not fastidiousness: a percentage recomputed here would
 * disagree with the server the moment a window's ends sat either side of a
 * methodology boundary, which is exactly when the honest answer is that there
 * is no percentage at all.
 *
 * IT COSTS NOTHING TO RENDER. The rows come from the analytics response the
 * band above is already holding, so a timeframe change updates the chart, the
 * headline and this section from ONE response - there is no second request
 * here, and no `/prices` call.
 *
 * SUBORDINATE TO THE CHART, AND DELIBERATELY SO. The plot is what a reader
 * came for and the archived headline is the page's one gold figure; this is
 * the detail underneath both. Hence a quiet ruled list rather than cards,
 * gauges, bars or a second chart.
 *
 * THIS IS NOT THE LIVE MARKET SECTION AND MUST NOT MERGE WITH IT. Everything
 * here describes the SELECTED HISTORICAL WINDOW, read from the archive. The
 * live section below describes what the sources say right now. Two different
 * questions, two sections, and the heading of each says which.
 *
 * THE THREE ROWS ARE NOT THREE COMPARABLE PRICES. Each keeps its own platform
 * name and its own instrument - Card Pirate's derived index, a dealer's retail
 * asking price, a marketplace's current listing floor - taken from the same
 * helpers the chart's chips use. Nothing here calls any of them a sale price,
 * a transaction price, an average or "the market price".
 */
export function PrintWindowPerformance({
  analytics,
  loading,
}: {
  /** The response the analytics band is already rendering, or null before the
   * first one lands. */
  analytics: PrintAnalytics | null;
  /** True until the first response for this print arrives. The print and its
   * analytics are two independent requests, so the page becomes `ready` on the
   * print alone - and without this, everything below would sit at the top of
   * the page and then jump down by a whole section when the analytics landed. */
  loading: boolean;
}) {
  const rows = analytics?.series_stats ?? [];

  // NOT YET, AS OPPOSED TO NOTHING. These are two different states and only
  // one of them reserves room. The headline two components up already had to
  // learn this (its `h-[92px]` placeholder exists for the same race); this is
  // the same fix applied to the section that now sits between it and
  // `LiveMarket`.
  if (rows.length === 0 && loading) return <WindowPerformanceSkeleton />;

  // A payload from a build that predates `series_stats`, a response that
  // failed, or a print with nothing drawable: the section simply does not
  // exist. The chart and the page above it are unaffected.
  if (rows.length === 0) return null;

  // Joined by key so each row gets the SAME display name the chart's chips
  // use, rather than a second naming rule that could drift from it.
  const byKey = new Map<string, PrintSeries>(
    (analytics?.series ?? []).map((entry) => [entry.key, entry]),
  );

  return (
    <section
      className="mt-7 border-t border-border-muted pt-5"
      data-testid="window-performance"
    >
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Window performance
      </h2>

      {/* Column headings on desktop only. On a phone each row carries its own
          labels, because a four-column table at 390px is either a horizontal
          scroller or four columns of truncation. */}
      <div className="mt-3 hidden border-b border-border-muted/60 pb-1.5 sm:grid sm:grid-cols-[minmax(0,1.15fr)_minmax(0,1.75fr)_minmax(0,1.15fr)_auto] sm:gap-x-5">
        {["Instrument", "Window move", "Range", "Observed"].map((label) => (
          <span
            key={label}
            className="mono text-[9px] uppercase leading-none tracking-[0.14em] text-text-faint"
          >
            {label}
          </span>
        ))}
      </div>

      {/* SERVER ORDER, untouched. Sorting these - by size of move, by platform,
          by anything - would be the client asserting a ranking the server did
          not publish, and a "biggest mover" reading the data does not support. */}
      <ul className="divide-y divide-border-muted/60">
        {rows.map((row) => (
          <PerformanceRow key={row.series_key} row={row} series={byKey.get(row.series_key)} />
        ))}
      </ul>

      <p className="mt-3 text-[10px] leading-snug text-text-faint">
        Figures describe the selected window of Atlas&rsquo;s recorded history. Current
        source prices are below.
      </p>
    </section>
  );
}

/** The room the section will take, held from the first frame.
 *
 * Three rows, because Market Index plus two sources is the common shape. A
 * print with fewer settles upward slightly, which is a far smaller movement
 * than the whole section appearing at once - and the alternative, guessing the
 * count before the response that decides it, is not available. Mute and
 * `aria-hidden`: it claims that something is coming, which is true, and nothing
 * about what.
 */
function WindowPerformanceSkeleton() {
  return (
    <section
      className="mt-7 border-t border-border-muted pt-5"
      aria-hidden="true"
      data-testid="window-performance-skeleton"
    >
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Window performance
      </h2>
      <div className="mt-3 h-[22px] border-b border-border-muted/60" />
      <div className="divide-y divide-border-muted/60">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-[46px]" />
        ))}
      </div>
      <div className="mt-3 h-[14px]" />
    </section>
  );
}

function PerformanceRow({
  row,
  series,
}: {
  row: PrintSeriesStats;
  series: PrintSeries | undefined;
}) {
  // The chart's own two helpers. `instrument` is null in three honest ways -
  // the Market Index is not quoted in an instrument, an unconfigured source
  // names none, and a series whose instrument CHANGED has more than one - and
  // the platform stands alone in each.
  const platform = series ? seriesPlatformLabel(series) : row.series_key;
  const instrument = series ? seriesInstrumentLabel(series) : null;

  return (
    <li className="grid grid-cols-1 gap-x-4 gap-y-1.5 py-3 sm:grid-cols-[minmax(0,1.15fr)_minmax(0,1.75fr)_minmax(0,1.15fr)_auto] sm:items-baseline sm:gap-y-0">
      <div className="min-w-0">
        <span className="text-[13px] font-medium text-text-primary">{platform}</span>
        {instrument && (
          <span className="text-[12px] text-text-muted"> · {instrument}</span>
        )}
      </div>

      <WindowMove row={row} />

      <Cell label="Range">
        <span className="mono tabular whitespace-nowrap text-[12px] text-text-secondary">
          {/* The observed low and high of THIS series in THIS window. It is not
              a claim that every value between them was seen, or traded. */}
          {formatJpy(row.low_value_jpy)} – {formatJpy(row.high_value_jpy)}
        </span>
      </Cell>

      <Cell label="Observed">
        <span className="mono tabular whitespace-nowrap text-[12px] text-text-secondary">
          {/* DAYS. Not observations, samples, trades, sales or volume - Atlas
              records no transaction anywhere, so there is none to report. */}
          {row.observed_days} {row.observed_days === 1 ? "day" : "days"}
        </span>
      </Cell>
    </li>
  );
}

/** Where the series started and where it ended, and the move between them -
 * or, where the server declined to subtract, why there is no move.
 *
 * THE ENDS ARE SHOWN EITHER WAY. A refused change is a statement about
 * COMPARABILITY, not about the observations: the series really did start at
 * ¥27,400 and really is at ¥22,900, and hiding those because the two cannot be
 * subtracted would withhold facts Atlas holds. What is withheld is only the
 * arithmetic the server would not do.
 *
 * A GENUINE ZERO IS A RESULT, NOT AN ABSENCE. `¥0 (0.00%)` means the series is
 * exactly where it started, and it renders as a published change like any
 * other - never as the unavailable state, which says something entirely
 * different.
 */
function WindowMove({ row }: { row: PrintSeriesStats }) {
  // NO WRAPPING INSIDE A NUMBER. At desktop column widths the browser broke
  // `−￥3,500` after its minus sign, leaving a bare `−` at the end of one line
  // and `￥3,500` at the start of the next - which reads as a completely
  // different figure. Each value is one unbreakable unit; the line may break
  // BETWEEN them.
  // THE END VALUE CARRIES ITS DAY. Without it, `→ ￥21,000` sits a short scroll
  // above a Live market card reading ￥21,000 under the identical instrument
  // label, and the two read as one fact stated twice. They are not: this is the
  // last day of the SELECTED WINDOW in the archive, and the one below is
  // resolved at request time. The date is the server's `current_as_of`, shown
  // the same way the headline stamps its own figures.
  const ends = (
    <>
      <span className="mono tabular whitespace-nowrap text-[12px] text-text-secondary">
        {formatJpy(row.starting_value_jpy)} → {formatJpy(row.current_value_jpy)}
      </span>{" "}
      {/* OUTSIDE the nowrap span on purpose. Held inside it, the stamp made
          the whole move unbreakable and the column overran into Range at
          desktop widths; out here it drops to its own line when it has to. */}
      <span className="mono whitespace-nowrap text-[10px] text-text-faint">
        {/* "As of", the same words the archived headline stamps its own
            figures with. One phrase for one kind of fact - a second preposition
            for the same thing is how two surfaces start describing one date
            differently. */}
        as of {formatDate(row.current_as_of)}
      </span>
    </>
  );

  if (row.change) {
    return (
      <Cell label="Window move">
        <span className="block" data-testid={`move-${row.series_key}`}>
          {ends}
          <span className="mono tabular ml-2 inline-block whitespace-nowrap text-[12px] text-text-primary">
            {formatSignedJpy(row.change.absolute_jpy)}
            <span className="ml-1.5 text-text-muted">
              ({formatSignedPct(row.change.pct)})
            </span>
          </span>
        </span>
      </Cell>
    );
  }

  // MUTED, NEVER AN ALARM. A window that crosses a methodology boundary is
  // Atlas being careful, not an error and not a fault in the card - so this
  // takes the quietest text tier and none of the operational red/amber
  // vocabulary. The reader never sees the raw token.
  //
  // SAID ONCE ON THE PAGE, NOT TWICE. The full sentence lives in the archived
  // headline above, which is the Market Index's own statement about itself;
  // repeating it verbatim a few rows later read as accidental rather than as
  // deliberate reinforcement. What survives here is the fact - this pair of
  // ends cannot be subtracted - in two words.
  //
  // THE EXPLANATION IS STILL REACHABLE, because a source series' refusal has
  // no counterpart above it: the headline speaks only for the Market Index, so
  // a SNKRDUNK instrument change would otherwise be an unexplained "Not
  // comparable". The server's own sentence rides on the title and the
  // accessible name rather than as a second block of body copy.
  const copy =
    changeUnavailableCopy(row.change_unavailable_reason) ??
    "No comparable change to report for this window.";
  return (
    <Cell label="Window move">
      <span className="block" data-testid={`move-${row.series_key}`}>
        {ends}
        <span
          className="mono ml-2 whitespace-nowrap text-[12px] text-text-muted"
          data-testid={`move-unavailable-${row.series_key}`}
          title={copy}
          aria-label={`Not comparable — ${copy}`}
        >
          Not comparable
        </span>
      </span>
    </Cell>
  );
}

/** One cell, with a label that only appears on a phone.
 *
 * The desktop grid has a header row, so repeating the label in every cell
 * would be four extra columns of noise. Stacked on a phone there is no header
 * to refer back to, so each value carries its own. */
function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 sm:block">
      <span className="mono w-[74px] shrink-0 text-[9px] uppercase leading-none tracking-[0.14em] text-text-faint sm:hidden">
        {label}
      </span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}
