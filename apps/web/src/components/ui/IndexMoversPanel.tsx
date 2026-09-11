"use client";

import Link from "next/link";

import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { RarityBadge } from "@/components/RarityBadge";
import { resolveCardImageUrl } from "@/lib/cardImage";
import { formatJpy } from "@/lib/format";
import {
  formatIndexDay,
  formatIndexPoints,
  formatRawPct,
  type IndexMover,
  type IndexMovers,
} from "@/lib/cardPirateIndex";

/** WHICH cards moved the Card Pirate Index on its newest published day.
 *
 * TWO COLUMNS BECAUSE THERE ARE TWO ANSWERS, and this panel is careful never
 * to let them collapse into one. "Price move" is what the CARD did, between
 * two archived Market Index values. "Index impact" is what the card did to the
 * INDEX, after the methodology's unconditional +/-25 % daily cap and a division
 * by the constituent count. They are the same story only on an uncapped day:
 * on 2026-09-07 a 41.18 % fall and a 25.00 % fall contributed exactly the same
 * amount, and a single merged figure would have had to discard one of those two
 * true statements. So they sit side by side, separately labelled, and the
 * capped rows say so.
 *
 * NOTHING HERE IS COMPUTED. Ranks, contributions, capped values, index points
 * and the ordering are all the server's, rendered as received. The list is not
 * sorted - `movers` arrives in `move_rank` order and is mapped in place - and
 * no arithmetic is performed on a price, a percentage or a log return. The two
 * formatters this file calls choose a sign glyph and a thousands separator and
 * do nothing else.
 *
 * IT DOES NOT MOVE WITH THE TIMEFRAME. Movers describe the newest published
 * point, the same point whether the chart above shows two weeks or everything,
 * so the panel takes no window prop and its request takes no window argument.
 * It also renders the movers API's OWN `as_of` rather than the chart's last
 * plotted day: if the two ever disagree, saying so is honest and quietly
 * relabelling one of them is not.
 *
 * NOT RED AND GREEN, for the reason MarketBreadthPanel states at length: the
 * signal palette is reserved for the admin surface. Direction uses the Atlas
 * mark's own gold-north / teal-south pairing, which carries no
 * profit-and-loss connotation and survives the common colour-vision
 * deficiencies. Direction is never the only channel - every figure carries an
 * explicit sign.
 */

const UP_COLOR = "var(--accent-gold)";
const DOWN_COLOR = "var(--accent-teal)";

function directionColor(direction: string): string {
  return direction === "up" ? UP_COLOR : DOWN_COLOR;
}

/** The small caption both metric columns wear.
 *
 * Above the figures rather than below them - the page's own stat tiles put the
 * label on top, and with two lines of value in the price column a trailing
 * label would leave the two columns' captions on different baselines. */
function ColumnLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="block text-[11px] font-medium leading-none text-text-muted">
      {children}
    </span>
  );
}

/** WHAT THE CARD DID. Two archived Market Index values and the server's own
 * percentage between them - never derived from the capped log return, because
 * the cap is an index rule and not a claim about the card. */
function PriceMove({ mover }: { mover: IndexMover }) {
  return (
    <div className="min-w-0 sm:w-[136px] sm:shrink-0" data-testid="mover-price-move">
      <ColumnLabel>Price move</ColumnLabel>
      <p className="mono mt-1.5 whitespace-nowrap text-[12px] tabular-nums text-text-secondary">
        {formatJpy(mover.prior_value_jpy)}
        <span aria-hidden="true" className="mx-1 text-text-faint">
          →
        </span>
        <span className="text-text-primary">{formatJpy(mover.current_value_jpy)}</span>
      </p>
      <p
        className="mono mt-1 text-[13px] font-medium tabular-nums"
        style={{ color: directionColor(mover.direction) }}
        data-testid="mover-raw-pct"
      >
        {formatRawPct(mover.raw_pct)}
      </p>
    </div>
  );
}

/** WHAT THE CARD DID TO THE INDEX.
 *
 * `approx_index_points` and nothing else, with the server's own four decimal
 * places and an explicit sign. It is described as approximate in the column's
 * own footnote and is never called exact or additive: the index chains
 * multiplicatively in level space, so these figures genuinely do not sum to
 * the day's level change. A value the server could not express as a number is
 * dropped rather than printed as NaN beside a real price. */
function IndexImpact({ mover }: { mover: IndexMover }) {
  const points = formatIndexPoints(mover.approx_index_points);
  return (
    <div className="min-w-0 sm:w-[116px] sm:shrink-0 sm:text-right" data-testid="mover-index-impact">
      <ColumnLabel>Index impact</ColumnLabel>
      <p
        className="mono mt-1.5 text-[13px] font-medium tabular-nums"
        style={{ color: directionColor(mover.direction) }}
        data-testid="mover-index-points"
      >
        {points ?? "—"}
        <span className="sr-only"> index points, approximate</span>
      </p>
      {/* QUIET, NOT ALARMIST. A capped move is ordinary methodology, not a
          fault in the card or the data, so the chip is a muted outline rather
          than a warning colour. Omitted entirely when nothing was capped. */}
      {mover.was_capped && (
        <span
          className="mono mt-1.5 inline-flex items-center rounded border border-border-default px-1.5 py-0.5 text-[9px] uppercase tracking-[0.12em] text-text-muted"
          data-testid="mover-capped"
        >
          Capped
        </span>
      )}
    </div>
  );
}

/** WHICH PRINT, not which card code.
 *
 * `card_code` does not identify a print - OP01-016 has seven in the catalogue
 * and one of them moved - so the row carries the artwork, the code, the
 * rarity, the language and the treatment when it has one. The image is the
 * only reliable disambiguator between parallel printings, `treatment` being
 * frequently null even on one. */
function MoverIdentity({ mover }: { mover: IndexMover }) {
  const name = mover.name ?? mover.card_code ?? "Unknown print";
  const code = mover.card_code ?? "—";
  return (
    <div className="min-w-0">
      <p className="truncate text-[13px] font-medium leading-snug text-text-primary">{name}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="mono text-[11px] text-text-secondary" data-testid="mover-card-code">
          {code}
        </span>
        {mover.rarity && <RarityBadge rarity={mover.rarity} />}
        {mover.language && (
          <span className="mono text-[10px] uppercase tracking-[0.1em] text-text-muted">
            {mover.language}
          </span>
        )}
        {mover.treatment && (
          <span className="text-[11px] text-text-muted">{mover.treatment}</span>
        )}
      </div>
    </div>
  );
}

/** One mover.
 *
 * Mobile is the artwork spanning both rows on the left, identity beside it,
 * and the two metric blocks side by side underneath - so the two concepts stay
 * visibly separate at 390px without either wrapping into the other. Desktop
 * promotes the same three blocks into one row of three columns, with fixed
 * metric widths so the figures form real columns down the list rather than
 * ragged text. */
function MoverRow({ mover }: { mover: IndexMover }) {
  return (
    <li
      className="group border-t border-border-muted first:border-t-0"
      data-testid="index-mover"
      data-card-print-id={mover.card_print_id}
    >
      <Link
        href={`/prints/${mover.card_print_id}`}
        prefetch={false}
        className="grid grid-cols-[56px_minmax(0,1fr)] items-start gap-x-3 gap-y-3 rounded-control py-3 transition-colors group-first:pt-0 hover:bg-bg-elevated active:bg-bg-elevated focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal sm:grid-cols-[64px_minmax(0,1fr)_auto] sm:items-center sm:gap-x-4"
      >
        {/* CONTAIN, NEVER COVER, and no geometry prop: the movers payload
            publishes none, so CardImageFrame takes its plain object-contain path
            and the whole card stays visible inside the 63:88 frame. The URL goes
            through the app's existing same-origin rewrite - Bandai's host sends
            Cross-Origin-Resource-Policy: same-site and would otherwise render
            nothing but the placeholder. */}
        {/* `size="full"` inside a wrapper of the grid track's own width, NOT the
            fixed `sm` size: `sm` is `w-20` (80px) with `shrink-0`, which
            overflowed this row's 56px track and rendered the frame on top of the
            card name beside it. Letting the frame fill a track-width wrapper
            keeps the two in step at both breakpoints. */}
        <div className="row-span-2 w-[56px] sm:row-span-1 sm:w-[64px]">
          <CardImageFrame
            imageUrl={resolveCardImageUrl(mover.display_image_url)}
            alt={`${mover.name ?? mover.card_code ?? "Card"} (${mover.card_code ?? "unknown print"})`}
            cardCode={mover.card_code ?? "—"}
            rarity={mover.rarity}
            size="full"
            padded
          />
        </div>
        <MoverIdentity mover={mover} />
        <div className="col-start-2 flex items-start gap-5 sm:col-start-3 sm:gap-6">
          <PriceMove mover={mover} />
          <IndexImpact mover={mover} />
        </div>
      </Link>
    </li>
  );
}

function MoversSkeleton() {
  return (
    <div className="mt-4 space-y-3" aria-busy="true">
      <span className="sr-only">Loading what moved the index…</span>
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-[63px] w-[46px] shrink-0 rounded bg-bg-elevated sm:w-[52px]" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-40 rounded bg-bg-elevated" />
            <div className="h-2.5 w-24 rounded bg-bg-elevated" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** A note, only when the day actually had one.
 *
 * The sentence exists to explain why a column disagrees with the column beside
 * it, so on a day nothing was capped there is nothing to explain and the line
 * would be noise a reader has to read to dismiss - the same rule Market
 * Breadth applies to its own capping row. */
function CappedNote() {
  return (
    <p
      className="mt-3.5 border-t border-border-muted pt-3 text-[11px] leading-relaxed text-text-faint"
      data-testid="movers-capped-note"
    >
      Large card moves are capped by the Index methodology, so price movement
      and Index impact may differ.
    </p>
  );
}

export function IndexMoversPanel({
  movers,
  status,
}: {
  movers: IndexMovers | null;
  status: "loading" | "ready" | "error";
}) {
  const ready = status === "ready" && movers !== null;
  const rows = ready ? movers.movers : [];
  const anyCapped = rows.some((m) => m.was_capped);
  /** A BASE POINT, which is not the same thing as a quiet day. It opened a
   * segment, so it came from no prior point and has no constituents at all -
   * "nothing moved" would be true but would imply a comparison that never
   * happened. */
  const isBasePoint = ready && movers.prior_point_date === null;

  return (
    <section
      id="latest-moves"
      aria-labelledby="index-movers-heading"
      data-testid="index-movers"
      className="mt-5 scroll-mt-[calc(var(--header-h)+1rem)] rounded-panel border border-border-muted bg-bg-surface p-4 sm:p-5"
    >
      <h3
        id="index-movers-heading"
        className="font-display text-[16px] font-semibold leading-tight tracking-tight text-text-primary"
      >
        What moved it?
      </h3>
      {/* The movers API's OWN as_of and constituent count. `movers_count` is
          the server's count over the FULL constituent set, so it stays correct
          on a day the payload is truncated - `movers.length` would quietly
          report how many rows fitted instead of how many moved. */}
      <p className="mt-1 text-[12px] leading-relaxed text-text-secondary" data-testid="movers-meta">
        {ready
          ? `${formatIndexDay(movers.as_of)} · ${movers.movers_count} of ${movers.constituent_count} constituents moved`
          : "The cards behind the latest index move."}
      </p>

      {status === "error" ? (
        // PANEL-LOCAL, like the composition panel's. The hero, the chart and
        // both panels above are built from other responses and keep rendering.
        <p
          className="mt-5 text-[12px] leading-relaxed text-text-muted"
          data-testid="movers-unavailable"
        >
          We can&apos;t show the cards behind this move right now.
        </p>
      ) : status === "loading" || movers === null ? (
        <MoversSkeleton />
      ) : isBasePoint ? (
        <p
          className="mt-5 text-[12px] leading-relaxed text-text-muted"
          data-testid="movers-base-point"
        >
          This is the starting point of the Card Pirate Index. There is no prior
          day to compare.
        </p>
      ) : rows.length === 0 ? (
        // NORMAL DATA, NOT AN ERROR. 296 constituents were all comparable and
        // every one of them held its price; a placeholder row or an empty
        // column would suggest something failed to load.
        <p
          className="mt-5 text-[12px] leading-relaxed text-text-muted"
          data-testid="movers-none"
        >
          No cards moved on this published day.
        </p>
      ) : (
        <>
          <ul className="mt-4" data-testid="movers-list">
            {rows.map((mover) => (
              <MoverRow key={mover.card_print_id} mover={mover} />
            ))}
          </ul>
          {movers.truncated && (
            <p
              className="mt-3 text-[11px] leading-relaxed text-text-muted"
              data-testid="movers-truncated"
            >
              Showing the {rows.length} largest moves of {movers.movers_count}.
            </p>
          )}
          {anyCapped && <CappedNote />}
          {/* Said once, in the panel, rather than beside every figure: the
              index points column is a rendering of each card's contribution
              scaled by the prior level, and the index chains multiplicatively,
              so the column genuinely does not add up to the day's move. */}
          <p className="mt-2 text-[11px] leading-relaxed text-text-faint">
            Index impact is approximate and does not sum to the day&rsquo;s Index
            change.
          </p>
        </>
      )}
    </section>
  );
}
