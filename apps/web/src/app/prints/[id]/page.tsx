"use client";

import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import {
  RarityTermBadge,
  SpecialPrintBadge,
  UnknownRarityBadge,
} from "@/components/RarityBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { ATLAS_MAP_TEXTURE_SRC } from "@/components/brand/AtlasBrandAssets";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { CatalogueLegend } from "@/components/ui/CatalogueLegend";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { MarketIndexValue } from "@/components/ui/MarketIndexValue";
import {
  PrintPriceHistorySection,
  type PriceHistoryStatus,
} from "@/components/ui/PrintPriceHistory";
import { InfoTip } from "@/components/ui/InfoTip";
import { SourceConstraintNote } from "@/components/ui/SourceConstraintNote";
import { SourceContributionNote } from "@/components/ui/SourceContributionNote";
import { ApiError } from "@/lib/api";
import { formatDate, formatJpy } from "@/lib/format";
import { buildPriceHistoryView, type PriceHistoryView } from "@/lib/printPriceHistory";
import {
  describeUnavailableSource,
  isUnavailableSourceValue,
  unavailableSourceValues,
} from "@/lib/sourceAvailability";
import {
  contributionQualifier,
  displayedSourceValues,
  rangeIncludesReferenceOnly,
  REFERENCE_ONLY_RANGE_CAPTION,
} from "@/lib/sourceContribution";
import {
  fetchPrint,
  fetchPrintPrices,
  sourceDisplayName,
  type PrintDetail,
  type PrintMarketIndex,
  type PrintMarketIndexSourceValue,
  type PrintUiModel,
  toPrintUiModel,
} from "@/lib/prints";
import { describeSourceEvidence } from "@/lib/sourceEvidence";
import { getTerm, type Term } from "@/lib/terminology";

/** The evidence type behind one source value: what kind of number this is,
 * and one sentence saying what it is not.
 *
 * A retail asking price, a dealer's buy quote, a median of completed sales and
 * the cheapest live listing are four different claims about a card, and this
 * page says which one it is showing rather than flattening them all into
 * "price". The wording lives in @/lib/sourceEvidence so it is written once
 * and matches whatever the API's `reference_type` says; an unrecognised type
 * falls through to the API's own string with no explanation rather than being
 * guessed at.
 *
 * NEUTRAL. Under Market Index v3 an eligible current listing counts toward the
 * index exactly like an eligible sold median, so this line is muted supporting
 * text in the panel's ordinary colour - no amber, no chip, nothing that reads
 * as a caveat. It answers "what am I looking at", not "what is wrong with
 * this". The genuinely excluding states - a platform-minimum listing, a stale
 * observation - keep their own louder vocabulary in SourceConstraintNote
 * directly beneath, and this line neither duplicates nor softens them.
 *
 * The explanation is a keyboard- and tap-operable disclosure rather than a
 * hover tooltip: most collectors read this page on a phone, where hover does
 * not exist. See InfoTip. */
function EvidenceTypeLine({ value }: { value: PrintMarketIndexSourceValue }) {
  const copy = describeSourceEvidence(value.reference_type);
  const label = copy?.label ?? value.reference_type;

  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-text-secondary">
      <span>
        {label}
        {value.sample_size !== null && ` · ${value.sample_size} sales`}
      </span>
      {copy && <InfoTip label={`About ${copy.label}`} text={copy.explanation} />}
    </p>
  );
}

/** Where the artwork on this page came from, when the API said.
 *
 * A collector inspecting a print should be able to see whether they are
 * looking at a verified image of this exact printing or the canonical card
 * list's watermarked scan. Both facts come straight from `display_image`. */
function imageProvenance(print: PrintUiModel): string | null {
  if (!print.imageSource) return null;
  // Every source name now resolves through the one shared mapping, including
  // "bandai" - the API's identifier for the official ONE PIECE Card List.
  const source = sourceDisplayName(print.imageSource);
  return print.imageExactPrintVerified
    ? `${source} image · verified for this printing`
    : `${source} image`;
}

/** The collector-facing print detail page.
 *
 * The card is the hero and everything else supports it: a large, uncropped
 * presentation on the left, then identity, then the money, then the print's
 * own metadata. Nothing on this page is a dashboard widget, because a
 * collector opening a card is inspecting an object, not monitoring a
 * position.
 *
 * Every value rendered here comes from this print's own `GET /prints/{id}`
 * payload, plus `GET /prints/{id}/prices` for the price-history section - both
 * scoped server-side to this `card_print_id`. The sections that exist are the
 * ones the API can actually fill. Sibling printings are the API's own
 * `siblings` list, never inferred from the catalogue.
 *
 * History is fetched separately and deliberately non-blocking: it is
 * supporting evidence, so the card, its identity and its Market Index render
 * as soon as the print itself arrives, and a history request that fails simply
 * leaves that one section out rather than erroring the page.
 */
export default function PrintDetailPage() {
  const params = useParams<{ id: string }>();
  const printId = params?.id;

  const [print, setPrint] = useState<PrintUiModel | null>(null);
  const [detail, setDetail] = useState<PrintDetail | null>(null);
  const [history, setHistory] = useState<PriceHistoryView | null>(null);
  const [historyStatus, setHistoryStatus] = useState<PriceHistoryStatus>("loading");
  const [status, setStatus] = useState<"loading" | "error" | "not_found" | "ready">("loading");

  useEffect(() => {
    if (!printId) return;
    let cancelled = false;
    setStatus("loading");
    // Cleared on every id change so a previous print's history can never be
    // shown beneath a newly-loaded print while its own request is in flight.
    setHistory(null);
    setHistoryStatus("loading");
    fetchPrint(printId)
      .then((result) => {
        if (cancelled) return;
        setDetail(result);
        setPrint(toPrintUiModel(result));
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // A print id that does not exist is a different fact from "the
        // catalogue is unreachable", and a collector who followed a stale
        // link deserves to be told which one happened rather than being
        // offered a Retry that can never succeed.
        setStatus(err instanceof ApiError && err.status === 404 ? "not_found" : "error");
      });
    fetchPrintPrices(printId)
      .then((result) => {
        if (cancelled) return;
        // The view model is built against the response's OWN card_print_id, so
        // the section can only ever describe the print the API answered for.
        const view = buildPriceHistoryView(result, result.card_print_id);
        setHistory(view);
        // A print no source has ever priced has no section to show, and the
        // placeholder must not sit there forever waiting for one.
        setHistoryStatus(view.series.length > 0 ? "ready" : "unavailable");
      })
      .catch(() => {
        // Supporting evidence: a history that cannot be loaded is a section
        // this page does without, not a page-level failure.
        if (cancelled) return;
        setHistory(null);
        setHistoryStatus("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [printId]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="relative isolate mx-auto max-w-6xl px-4 py-4">
        {/* The same cartography as the catalogue intro, at a fraction of the
            strength and only behind the top of the page: enough to place the
            card on the Atlas's own surface, not enough to notice as a
            texture. Screened so only the drawn lines survive, then washed out
            to the page colour before the metadata section begins. */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[460px]">
          <Image
            src={ATLAS_MAP_TEXTURE_SRC}
            data-brand-asset=""
            alt=""
            fill
            sizes="100vw"
            className="object-cover object-right-top opacity-[0.18] mix-blend-screen"
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(23,23,23,0.7)_0%,rgba(23,23,23,0.92)_62%,rgba(23,23,23,1)_100%)]" />
        </div>

        {/* The catalogue is the only place this page came from and the only
            place it links back to. */}
        <Link
          href="/cards"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-text-muted transition-colors hover:text-accent-teal"
        >
          <span aria-hidden="true">←</span> Catalogue
        </Link>

        {status === "loading" && (
          <div className="mt-4">
            <LoadingState>Loading this print…</LoadingState>
          </div>
        )}
        {status === "not_found" && (
          <div className="mt-4">
            <CollectorEmptyState
              title="This print isn’t in the Atlas."
              action={
                <Link
                  href="/cards"
                  className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover"
                >
                  Browse the catalogue →
                </Link>
              }
            >
              The link may be out of date, or this printing hasn’t been catalogued yet.
            </CollectorEmptyState>
          </div>
        )}
        {status === "error" && (
          <div className="mt-4">
            <ErrorState tone="collector">
              This print couldn’t be loaded right now.
            </ErrorState>
          </div>
        )}

        {status === "ready" && print && detail && (
          <article className="mt-4">
            {/* 40/60 on desktop: the card is the hero, but the money and the
                identity beside it stay above the fold rather than being
                pushed down by a pedestal. One column below `lg`, in the
                stacking order a phone should read it in. */}
            <div className="grid gap-7 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10">
              <CardStage print={print} />

              {/* Everything a collector reads about this print lives in one
                  column, metadata included. The card is much taller than the
                  identity and the money alone, and leaving the attributes in a
                  full-width band underneath left a dead block of column beside
                  the lower half of the artwork. */}
              <div className="min-w-0">
                <Identity print={print} />
                <MarketIndexBlock print={print} />
                <SourcePanels sources={print.marketIndex.source_values} />
                <PrintPriceHistorySection status={historyStatus} view={history} />
                <AboutThisPrint print={print} detail={detail} />
              </div>
            </div>

            {/* Genuinely secondary, and about *other* prints rather than this
                one - so it sits under both columns rather than inside the
                column describing the print in hand. */}
            <OtherPrintings siblings={detail.siblings} />
          </article>
        )}
      </main>
    </div>
  );
}

/** The card itself, as large as the column allows.
 *
 * Presentation is `CardImageFrame` exactly as the catalogue uses it - same
 * exact-print image, same verified geometry, same natural-size guard, same
 * no-crop contract - so this page cannot show a different card, a differently
 * framed card, or a card missing an edge. The surround is one charcoal panel,
 * a hairline border and a soft shadow: no slab, no grading case, no gold
 * frame, nothing that pretends to be part of the card.
 *
 * Widths are the whole point of the tranche. `max-w-[380px]` with the panel's
 * own 12px inset renders the card ~356px wide on desktop and ~276px on a
 * 390px phone, where it stays the largest thing on screen without swallowing
 * the viewport.
 */
function CardStage({ print }: { print: PrintUiModel }) {
  const provenance = imageProvenance(print);

  return (
    <div className="mx-auto w-full max-w-[300px] sm:mx-0 sm:max-w-[340px] lg:max-w-[380px]">
      <div className="rounded-panel-lg border border-border-muted bg-bg-elevated p-3 shadow-[0_20px_44px_-26px_rgba(0,0,0,0.95)]">
        <CardImageFrame
          imageUrl={print.imageUrl}
          alt={`${print.displayName} (${print.cardCode})`}
          cardCode={print.cardCode}
          rarity={print.rarity}
          setCode={print.releaseCode}
          size="full"
          padded
          geometry={print.imageGeometry}
        />
      </div>
      {provenance && (
        <p className="mt-2.5 text-center text-xs leading-snug text-text-muted sm:text-left">
          {provenance}
        </p>
      )}
    </div>
  );
}

/** Name, then the print's own identifiers.
 *
 * The treatment is always rendered, in the API's own word, including
 * "normal" - two printings of one card are two separate collectible objects
 * here, and this page is where a collector confirms which one they are
 * looking at. Nothing is renamed to "base" or inferred; a plain printing just
 * gets a quiet chip instead of the gold one a distinct treatment earns. An
 * unclassified printing (treatment null) gets no chip at all rather than a
 * made-up word - the rest of its identity renders unchanged.
 */
function Identity({ print }: { print: PrintUiModel }) {
  return (
    <header>
      <h1 className="font-display text-[30px] font-semibold leading-[1.05] tracking-tight text-text-primary sm:text-[38px]">
        {print.displayName}
      </h1>

      {print.nameJp && print.nameJp !== print.displayName && (
        <p lang="ja" className="mt-1.5 text-base text-text-secondary sm:text-lg">
          {print.nameJp}
        </p>
      )}

      <div className="mono mt-3 flex flex-wrap items-center gap-x-2 text-xs text-text-muted">
        <span>{print.cardCode}</span>
        {print.releaseCode && (
          <>
            <span aria-hidden="true">·</span>
            {/* "Found in", never "Set": for a reprint this is a later product
                than the set the card came from. The true set has its own row
                in "About this print". */}
            <span>
              <span className="text-text-faint">Found in </span>
              {print.releaseCode}
            </span>
          </>
        )}
      </div>

      {/* Rarity, then special print, then printing - the same three
          dimensions, in the same order, as the "About this print" rows below,
          so the badges and the list never read as two different accounts of
          the card. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {print.rarityTerm && <RarityTermBadge term={print.rarityTerm} />}
        {print.specialPrint && <SpecialPrintBadge term={print.specialPrint} />}
        {print.unknownRarityToken && <UnknownRarityBadge token={print.unknownRarityToken} />}
        {print.printingType && (
          <span
            className="mono inline-flex rounded border border-accent-gold/30 bg-accent-gold/10 px-2 py-0.5 text-[11px] font-medium tracking-wide text-accent-gold"
            title={`${print.printingType.label} — ${print.printingType.definition}`}
          >
            {print.printingType.label}
          </span>
        )}
      </div>
    </header>
  );
}

/** The monetary focal point: the same caption-over-gold-value language the
 * catalogue tile established, one size up because this page has the room.
 *
 * Coverage is stated by the source panels directly below - one panel per
 * source that actually reported, named and priced - rather than by a chip, so
 * a one-source index can never read as a two-source consensus and the page
 * keeps to the collector palette instead of the operational green/amber one.
 * `MarketIndexValue` still renders its own
 * stale warning, and a null index still says "Index unavailable" rather than
 * ¥0. There is no change figure, arrow or chart, because the payload carries
 * no history to draw one from.
 */
function MarketIndexBlock({ print }: { print: PrintUiModel }) {
  return (
    <section className="mt-7 border-t border-border-muted pt-5">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Market Index
      </h2>
      <div className="mt-2">
        <MarketIndexValue
          index={print.marketIndex}
          size="lg"
          tone="gold"
          showCoverage={false}
        />
      </div>
      <SourceContributionQualifier index={print.marketIndex} />
      <SourcePriceRange
        range={print.marketIndex.source_price_range}
        includesReferenceOnly={rangeIncludesReferenceOnly(print.marketIndex.source_values)}
      />
      {print.latestObservationAt && (
        <p className="mt-2 text-[11px] text-text-faint">
          Updated {formatDate(print.latestObservationAt)}
        </p>
      )}
    </section>
  );
}

/** "1 of 2 source prices used" - the one line that reconciles a ¥120 index
 * sitting beside a visible ¥2,500 source price.
 *
 * Since Market Index v2 an admissible fallback source stands aside from the
 * aggregate whenever a non-fallback value is present, so the panels below can
 * legitimately show more prices than the index was computed from. Without
 * this line the page states two numbers and denies the reader any way to see
 * that both are correct.
 *
 * The numerator is the index's own `source_count` - the count it published
 * for itself - not a tally this page reconstructs from the source rows. See
 * @/lib/sourceContribution for why: a second implementation of the
 * contributor rule, running in a browser, is free to disagree with the number
 * it sits beneath.
 *
 * A count, not a judgement: no percentage, no spread, no warning, no claim
 * about which price is right. It renders only when the two counts actually
 * differ, so the ordinary two-contributor print gains nothing to read, and it
 * is 11px metadata beneath the gold figure, which stays the only number on
 * this page with weight. */
function SourceContributionQualifier({ index }: { index: PrintMarketIndex }) {
  const qualifier = contributionQualifier(index);
  if (!qualifier) return null;

  return (
    <p className="mt-1.5 text-[11px] leading-snug text-text-secondary">{qualifier}</p>
  );
}

/** How far apart the sources behind the index above actually were.
 *
 * The index alone cannot say: with two sources it is their midpoint, and a
 * midpoint reads identically whether the sources agreed within 5% or disagreed
 * by tenfold. One quiet line answers that at the moment of doubt, in the same
 * 11px metadata scale as the "Updated ..." caption beneath it, so the gold
 * index value stays the only figure on this page with weight.
 *
 * Every decision here belongs to the backend. Which values were eligible,
 * which is low and which is high, and whether a range exists at all arrive
 * decided in `source_price_range`; this component renders two numbers and
 * never computes a minimum, a threshold, or a spread. Absent, null, or a
 * single eligible source (the backend sends null below two) renders nothing
 * at all rather than a self-referential "X to X".
 *
 * Equal endpoints print once: two sources landing on the same yen figure is a
 * real, measured agreement, and "¥1,500 - ¥1,500" would only look broken. */
function SourcePriceRange({
  range,
  includesReferenceOnly,
}: {
  range: PrintMarketIndex["source_price_range"];
  /** Whether an endpoint of this span is a price that did not feed the index.
   * Decided by the caller from `contributes_to_index`; this component still
   * computes nothing. */
  includesReferenceOnly: boolean;
}) {
  if (!range) return null;

  const { low_jpy, high_jpy } = range;
  return (
    <>
      <p className="mt-1.5 text-[11px] leading-snug text-text-secondary">
        Source range{" "}
        <span className="mono tabular">
          {low_jpy === high_jpy
            ? formatJpy(low_jpy)
            : `${formatJpy(low_jpy)} – ${formatJpy(high_jpy)}`}
        </span>
      </p>
      {/* The range is built from every ADMISSIBLE value, before the v2
          contributor filter, so its endpoints can include a price the index
          did not use. Saying so is what keeps "Source range ¥120 - ¥2,500"
          beside a ¥120 index from reading as a contradiction. */}
      {includesReferenceOnly && (
        <p className="mt-0.5 text-[11px] leading-snug text-text-faint">
          {REFERENCE_ONLY_RANGE_CAPTION}
        </p>
      )}
    </>
  );
}

/** What one source that reported no price says, in place of the price.
 *
 * TWO DIFFERENT CLAIMS, WRITTEN DIFFERENTLY. "Price unavailable" is the honest
 * default when we do not know why a number is missing. When the backend does
 * know - `insufficient_sold_and_no_floor`, SNKRDUNK's own verdict that it read
 * the product and found nothing on offer - the panel says "No current listing"
 * instead, because that is a fact about the marketplace rather than a fact
 * about our data, and a collector reads the two very differently. The choice is
 * made in @/lib/sourceAvailability from the published reason; nothing here
 * inspects the source's name or infers a state from a null.
 *
 * THE DISCLOSURE EXISTS TO STOP A MISREADING. "No current listing" beside a
 * card that another shop prices could be taken as a verdict on the card's
 * worth. It is not one - a card can be scarce, expensive and simply not
 * individually listed today - so the sentence saying so is one tap or one
 * Enter away, in the same keyboard- and touch-operable disclosure the evidence
 * labels above use. See InfoTip.
 *
 * Still no number, no evidence label, no constraint note and no contribution
 * note: there is no price here for any of them to describe. */
function UnavailablePriceLine({ value }: { value: PrintMarketIndexSourceValue }) {
  const copy = describeUnavailableSource(value);

  return (
    /* Sentence case in the secondary colour at body scale, not the 20px
       tabular mono a price gets: the panel must read as a statement about this
       source, never scan as a figure. */
    <p className="mt-2 flex flex-wrap items-center gap-1.5 text-sm text-text-secondary">
      <span>{copy.label}</span>
      {copy.explanation && (
        <InfoTip label={`About ${copy.label}`} text={copy.explanation} />
      )}
    </p>
  );
}

/** The real per-source values behind the index, each labelled with what it
 * actually is - and, beside them, the sources that reported nothing.
 *
 * The panels *are* the coverage statement, which is why a source with no price
 * gets one too: it is named, and its panel says "Price unavailable" instead of
 * a figure. Never ¥0, never a dash, never an empty panel - each of those is a
 * price-shaped mark standing where a price belongs, and the honest claim here
 * is a sentence saying there is no price to show. Without it, a print priced by
 * one shop and not the other looked exactly like a print only one shop had ever
 * been asked about.
 *
 * An unavailable panel appears only when another source on this print did
 * report a number, so a print no source priced still shows no "Market sources"
 * section at all and "Index unavailable" above stands as the single statement -
 * see @/lib/sourceAvailability. Priced panels come first, in the API's order.
 *
 * An unavailable panel carries the source name and that one sentence, and
 * nothing else: the evidence type, the observation date, the constraint note
 * and the contribution note all describe a NUMBER, and there is no number here
 * for them to be about. Nothing is derived: the price, its reference type, when
 * it was observed and its sample size (when the value is a median of sales) all
 * ride on the same `source_values` entry.
 */
function SourcePanels({ sources }: { sources: PrintMarketIndexSourceValue[] }) {
  const rows = [...displayedSourceValues(sources), ...unavailableSourceValues(sources)];
  if (rows.length === 0) return null;

  return (
    <section className="mt-5">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Market sources
      </h2>
      <div className={`mt-3 grid gap-3 ${rows.length > 1 ? "sm:grid-cols-2" : "sm:grid-cols-1"}`}>
        {rows.map((row) => (
          <div
            key={`${row.source}-${row.reference_type}`}
            className="rounded-panel border border-border-muted bg-bg-elevated/70 px-3.5 py-3"
          >
            <div className="mono flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-text-muted">
              <span>{sourceDisplayName(row.source)}</span>
              {row.stale && (
                <span className="rounded bg-signal-warning/15 px-1 py-px text-[9px] normal-case tracking-normal text-signal-warning">
                  stale
                </span>
              )}
            </div>
            {isUnavailableSourceValue(row) ? (
              <UnavailablePriceLine value={row} />
            ) : (
              <>
                <div className="mono tabular mt-2 text-xl font-semibold text-text-primary">
                  {formatJpy(row.value_jpy)}
                </div>
                <EvidenceTypeLine value={row} />
                {row.observed_at && (
                  <p className="mt-0.5 text-[11px] text-text-faint">
                    Seen {formatDate(row.observed_at)}
                  </p>
                )}
                <SourceConstraintNote value={row} />
                <SourceContributionNote value={row} />
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/** The API's own `siblings` for this print - other printings of the same
 * card, each with its own detail page.
 *
 * Rendered only when the payload actually carries them. Nothing here is
 * derived from the catalogue or from artwork keys client-side: if the API
 * says a print has no siblings, this page says nothing about siblings.
 *
 * A sibling with no treatment is skipped entirely. The treatment is this
 * chip's only text, and this transitional treatment-keyed navigation has no
 * honest label for an unclassified printing - so it says nothing rather than
 * inventing one. Sibling identity is revisited after the final exact-print
 * identity migration.
 */
function OtherPrintings({ siblings }: { siblings: PrintDetail["siblings"] }) {
  const labelled = siblings.filter((sibling) => sibling.treatment);
  if (labelled.length === 0) return null;

  return (
    <section className="mt-10 border-t border-border-muted pt-6">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Other printings
      </h2>
      <div className="mt-3 flex flex-wrap gap-2">
        {labelled.map((sibling) => (
          <Link
            key={sibling.card_print_id}
            href={`/prints/${sibling.card_print_id}`}
            className="mono rounded-control border border-border-default bg-bg-elevated px-2.5 py-1.5 text-xs lowercase text-text-secondary transition-colors hover:border-accent-teal/50 hover:text-text-primary"
          >
            {sibling.treatment}
          </Link>
        ))}
      </div>
    </section>
  );
}

/** The print's own attributes, secondary to the card and the price.
 *
 * Sits at the foot of the identity column rather than in a full-width band
 * below, so on desktop it fills the column beside the lower half of the card
 * instead of leaving it empty. It is the same list either way: on a phone the
 * column is the page, and this still reads last, after the source prices.
 *
 * A plain two-column definition list rather than a grid of stat boxes, and
 * strictly the fields `GET /prints/{id}` returns - there is no cost, power,
 * attribute or effect text in that payload, so there are no rows for them.
 * Every row is omitted rather than dashed when its value is absent.
 */
function AboutThisPrint({ print, detail }: { print: PrintUiModel; detail: PrintDetail }) {
  // Six separate facts, deliberately not collapsed into one another, in the
  // order a collector reads them: which card this is, where the card came
  // from, where THIS printing turned up, how scarce the card is, whether the
  // printing is a special category, and which printing it is.
  //
  // "Set" and "Found in" are different products for a reprint, and only one of
  // them is the card's origin - so "Set" appears only when the API genuinely
  // has an `original_set_code`, and never borrows the release product to fill
  // the row. "Rarity" appears only when an ordinary rarity is actually
  // established for the card (see rarityFacts in lib/prints.ts): a Treasure
  // Rare whose card-level rarity the catalogue never settled gets no Rarity
  // row at all rather than a guess. Nothing here is dashed or defaulted - an
  // absent value is an absent row.
  const rows: { term: string; value: string; hint?: string }[] = [
    { term: "Card code", value: print.cardCode },
    ...termRow("Set", print.originalSetCode, getTerm("identity.set")),
    ...termRow("Found in", print.releaseCode, getTerm("identity.found_in")),
    ...termRow(
      "Rarity",
      print.rarityTerm?.label ?? null,
      print.rarityTerm,
      // Said out loud rather than left implicit: on an SP Card this rarity is
      // the card's, read from its own set, not a token printed on this
      // printing's catalogue entry - which is the whole reason it can sit
      // beside "SP Card" without the two contradicting each other.
      print.rarityIsCardLevel ? "The card's rarity, from its own set." : undefined,
    ),
    ...termRow("Special print", print.specialPrint?.label ?? null, print.specialPrint),
    ...termRow("Printing", print.printingType?.label ?? null, print.printingType),
    // The fail-safe: a rarity token this build cannot classify is still
    // published evidence, so it is shown verbatim under a heading that claims
    // nothing about what it means.
    ...termRow("Published rarity", print.unknownRarityToken, null),
    ...(print.cardType ? [{ term: "Card type", value: print.cardType }] : []),
    ...(detail.colors && detail.colors.length > 0
      ? [{ term: detail.colors.length > 1 ? "Colours" : "Colour", value: detail.colors.join(" · ") }]
      : []),
    ...(print.language
      ? [{ term: "Language", value: print.language.toLowerCase() === "jp" ? "Japanese" : print.language.toUpperCase() }]
      : []),
  ];

  return (
    <section className="mt-7 border-t border-border-muted pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
          About this print
        </h2>
        {/* The same key as the catalogue, on the page where a collector is
            most likely to be asking what "SP Card" is next to "Super Rare".
            The row hints below are a mouse-only enhancement; this is the
            route that works on a phone and from the keyboard. */}
        <CatalogueLegend />
      </div>
      <dl className="mt-4 grid gap-x-10 gap-y-2.5 sm:grid-cols-2">
        {rows.map((row) => (
          <div
            key={row.term}
            title={row.hint}
            className="flex items-baseline justify-between gap-4 border-b border-border-muted/60 pb-2.5"
          >
            <dt className="text-xs text-text-muted">{row.term}</dt>
            <dd className="text-sm text-text-secondary">{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** One "About this print" row, or none at all when the value is absent.
 *
 * Every row on this page is omitted rather than dashed when it has no value,
 * and doing that inline for six rows buried the rule in ternaries. The `hint`
 * is the term's own definition plus, where the term records one, the raw token
 * Bandai published - which is the one place a collector can still see
 * "SPカード" and understand where "SP Card" came from.
 */
function termRow(
  label: string,
  value: string | null,
  term: Term | null,
  note?: string,
): { term: string; value: string; hint?: string }[] {
  if (!value) return [];
  if (!term) return [{ term: label, value }];
  // The raw token is quoted only for a special print, which is the one case
  // where it is a different vocabulary rather than the label abbreviated:
  // "SPカード" explains where "SP Card" came from. Beside "Super Rare",
  // 'published as "SR"' would be noise - and on an SP print it would be wrong,
  // because that rarity came from the card, not from this catalogue entry.
  const raw = term.category === "special_print" ? term.sourceLabel : undefined;
  // ...and only where the token is not simply the label already on screen:
  // 'published as "TR"' beside a TR badge says nothing, whereas "SPカード"
  // is the one place a collector learns where "SP Card" came from.
  const worthSaying = raw && raw !== term.label && raw !== term.shortLabel;
  const provenance = worthSaying ? ` Published as "${raw}".` : "";
  return [{ term: label, value, hint: `${term.definition}${provenance}${note ? ` ${note}` : ""}` }];
}
