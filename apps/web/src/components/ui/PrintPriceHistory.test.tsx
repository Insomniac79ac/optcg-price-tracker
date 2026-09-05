/** What a collector actually reads in the "Price history" section.
 *
 * The chart itself is Recharts inside a ResponsiveContainer, which measures 0
 * in jsdom and therefore draws no path here - so these tests assert the things
 * that are true regardless of layout: which copy each series state produces,
 * that a constrained value is explained rather than plotted, and that a null
 * change window leaves no cell behind. The geometry invariant that a line is
 * never stroked through a constrained point is asserted structurally in
 * lib/printPriceHistory.test.ts, where the segments are decided.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PrintPriceHistory, PrintPriceHistorySection } from "./PrintPriceHistory";
import { buildPriceHistoryView } from "@/lib/printPriceHistory";
import type {
  PrintSeries,
  PrintSeriesHistory,
  PrintSeriesPoint,
  PrintSeriesSegment,
  PrintSeriesWindow,
} from "@/lib/printSeries";
import type { PrintPriceHistory as PrintPriceHistoryPayload, PrintPriceObservation } from "@/lib/prints";

let nextId = 1;

function observation(
  overrides: Partial<PrintPriceObservation> & Pick<PrintPriceObservation, "observed_at">,
): PrintPriceObservation {
  return {
    id: nextId++,
    card_print_id: 11,
    source_id: 1,
    source: "yuyutei",
    price_type: "sell",
    price_jpy: 1980,
    condition_label: null,
    listing_count: null,
    raw_snapshot_id: 1,
    constraint: null,
    eligible: true,
    ineligible_reason: null,
    // The server's instrument for this row, supplied independently of
    // `price_type` - the component's label comes from here, and nothing on
    // the path derives one from the other.
    reference_type: "retail_sell",
    evidence_type: "listing",
    ...overrides,
  };
}

/** The evidence rows on their own - no `/series` payload, which is the state
 * the page is in while the chart request is still out. */
function renderHistory(payload: PrintPriceHistoryPayload, cardPrintId = 11) {
  return render(
    <PrintPriceHistory
      view={buildPriceHistoryView(payload, cardPrintId)}
      series={null}
      seriesLoading={false}
      window="30d"
      onWindowChange={() => {}}
    />,
  );
}

describe("PrintPriceHistory", () => {
  it("names each source series and shows its latest price", () => {
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 7980 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 9980 }),
      ],
      series: [
        {
          source: "yuyutei",
          price_type: "sell",
          latest_price_jpy: 9980,
          latest_observed_at: "2026-08-02T00:00:00Z",
          sufficient_history: true,
          change_24h_pct: 25.06,
          change_7d_pct: null,
          change_30d_pct: null,
        },
      ],
    });

    expect(screen.getByRole("heading", { name: "Price history" })).toBeInTheDocument();
    expect(screen.getAllByText("Yuyu-Tei · Retail price").length).toBeGreaterThan(0);
    expect(screen.getByText("￥9,980")).toBeInTheDocument();
  });

  it("shows only the change windows the backend supplied", () => {
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({ observed_at: "2026-08-01T00:00:00Z" }),
        observation({ observed_at: "2026-08-02T00:00:00Z" }),
      ],
      series: [
        {
          source: "yuyutei",
          price_type: "sell",
          latest_price_jpy: 1980,
          latest_observed_at: "2026-08-02T00:00:00Z",
          sufficient_history: true,
          change_24h_pct: 0,
          change_7d_pct: null,
          change_30d_pct: null,
        },
      ],
    });

    // A genuine zero is a measurement and is reported as one...
    expect(screen.getByText("24h")).toBeInTheDocument();
    expect(screen.getByText("0.00%")).toBeInTheDocument();
    // ...while the null windows leave no cell, no dash and no 0% placeholder.
    expect(screen.queryByText("7d")).not.toBeInTheDocument();
    expect(screen.queryByText("30d")).not.toBeInTheDocument();
  });

  it("asks for more history instead of drawing a trend from one date", () => {
    renderHistory({
      card_print_id: 11,
      observations: [observation({ observed_at: "2026-08-30T00:00:00Z", price_jpy: 14000 })],
      series: [],
    });

    expect(screen.getByText(/More history needed for a trend/)).toBeInTheDocument();
    expect(screen.queryByTestId("price-history-chart")).not.toBeInTheDocument();
    expect(screen.getByText("￥14,000")).toBeInTheDocument();
  });

  it("explains a wholly constrained SNKRDUNK series rather than pricing it", () => {
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({
          observed_at: "2026-08-29T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 1000,
          constraint: "platform_floor",
          eligible: false,
          ineligible_reason: "platform_floor",
        }),
        observation({
          observed_at: "2026-08-30T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 1000,
          constraint: "platform_floor",
          eligible: false,
          ineligible_reason: "platform_floor",
        }),
      ],
      series: [],
    });

    expect(screen.getByText("SNKRDUNK · Current listing")).toBeInTheDocument();
    // The raw value stays visible - it is what the source really published.
    expect(screen.getByText("￥1,000")).toBeInTheDocument();
    // ...described with the existing constraint vocabulary, not a new one.
    expect(screen.getByText("Minimum listing price")).toBeInTheDocument();
    // One paragraph: the span this section contributes, then the verdict.
    expect(screen.getByText(/Not treated as a market price/)).toBeInTheDocument();
    expect(screen.getByText(/2 readings/)).toBeInTheDocument();
    // No chart, so no ¥1,000 line.
    expect(screen.queryByTestId("price-history-chart")).not.toBeInTheDocument();
  });

  it("says the chart is unavailable rather than claiming the print has no history", () => {
    // /prices answered and /series did not. The rows are real evidence and
    // stay; the chart's absence is stated as the chart's problem, because
    // "no recorded price history" would be a claim about the card that these
    // very rows contradict.
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 7980 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 9980 }),
      ],
      series: [],
    });

    expect(screen.getByTestId("price-history-empty")).toHaveTextContent(
      "Price chart unavailable right now.",
    );
    expect(screen.getByText("￥9,980")).toBeInTheDocument();
  });

  it("mixes a plotted series and a constrained one on the same print", () => {
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 220 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 240 }),
        observation({
          observed_at: "2026-08-02T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 1000,
          constraint: "platform_floor",
          eligible: false,
          ineligible_reason: "platform_floor",
        }),
      ],
      series: [],
    });

    // Two rows, two different sentences: a measured series and an explained
    // one, on the same print.
    expect(screen.getByText(/Not treated as a market price/)).toBeInTheDocument();
    expect(screen.getAllByText("SNKRDUNK · Current listing")).toHaveLength(1);
    expect(screen.getAllByText("Yuyu-Tei · Retail price")).toHaveLength(1);
    expect(screen.getByText("￥240")).toBeInTheDocument();
  });

  it("renders nothing at all when no source reported for this print", () => {
    const { container } = renderHistory({
      card_print_id: 11,
      observations: [],
      series: [],
    });

    expect(container).toBeEmptyDOMElement();
  });
});

describe("PrintPriceHistorySection", () => {
  it("reserves the section's space while history is still loading", () => {
    // The print and its history are two requests. Without a placeholder the
    // real section drops in afterwards and shoves the rest of the page down.
    const { container } = render(
      <PrintPriceHistorySection
        status="loading"
        view={null}
        series={null}
        seriesLoading
        window="30d"
        onWindowChange={() => {}}
      />,
    );

    // Queried by text, not by role: the placeholder is aria-hidden on purpose,
    // so a screen reader is never handed an empty skeleton to announce.
    expect(screen.getByText("Price history")).toBeInTheDocument();
    expect(container.querySelector("section")).toHaveAttribute("aria-hidden", "true");
    // Mute: it claims something is coming, and nothing about what.
    expect(container.textContent).not.toMatch(/￥|%|More history/);
  });

  it("renders nothing once history is known to be unavailable", () => {
    const { container } = render(
      <PrintPriceHistorySection
        status="unavailable"
        view={null}
        series={null}
        seriesLoading={false}
        window="30d"
        onWindowChange={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("reports how long a source has been at its constrained value", () => {
    render(
      <PrintPriceHistorySection
        status="ready"
        view={buildPriceHistoryView(
          {
            card_print_id: 11,
            observations: [
              observation({
                observed_at: "2026-08-20T00:00:00Z",
                source: "snkrdunk",
                source_id: 2,
                price_type: "floor",
                reference_type: "listing_floor",
                price_jpy: 1000,
                constraint: "platform_floor",
                eligible: false,
                ineligible_reason: "platform_floor",
              }),
              observation({
                observed_at: "2026-08-31T00:00:00Z",
                source: "snkrdunk",
                source_id: 2,
                price_type: "floor",
                reference_type: "listing_floor",
                price_jpy: 1000,
                constraint: "platform_floor",
                eligible: false,
                ineligible_reason: "platform_floor",
              }),
            ],
            series: [],
          },
          11,
        )}
        series={null}
        seriesLoading={false}
        window="30d"
        onWindowChange={() => {}}
      />,
    );

    // The span is what this section knows that the Market Index source panel
    // above it does not - so the row is not a second copy of that panel.
    expect(screen.getByText(/2 readings, Aug 20, 2026 – Aug 31, 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Not treated as a market price/)).toBeInTheDocument();
  });
});


// --- The chart's own controls ----------------------------------------------
//
// Recharts inside a ResponsiveContainer measures 0 in jsdom and draws no path,
// so these assert what is true regardless of layout: which platforms the
// reader is offered, what turning one off does to the model behind the chart,
// which windows exist, and what the section is never allowed to say. The line
// geometry itself is asserted in lib/printSeries.test.ts, where it is decided.

function seriesPoint(
  day: string,
  valueJpy: number | null,
  extra: Partial<PrintSeriesPoint> = {},
): PrintSeriesPoint {
  return { t: `${day}T02:00:00Z`, day, value_jpy: valueJpy, ...extra };
}

function seriesSegment(
  points: PrintSeriesPoint[],
  overrides: Partial<PrintSeriesSegment> = {},
): PrintSeriesSegment {
  return {
    reference_type: null,
    evidence_type: null,
    index_version: null,
    source_semantics_version: null,
    points,
    ...overrides,
  };
}

function seriesEntry(
  overrides: Partial<PrintSeries> & Pick<PrintSeries, "key" | "kind">,
): PrintSeries {
  const segments = overrides.segments ?? [];
  const points = segments.flatMap((entry) => entry.points);
  return {
    source: null,
    role: "primary",
    available: points.length > 0,
    unavailable_reason: points.length > 0 ? null : "no_history_in_window",
    breaks: [],
    coverage: {
      earliest: points[0]?.t ?? null,
      latest: points[points.length - 1]?.t ?? null,
      distinct_days: new Set(points.map((p) => p.day)).size,
      point_count: points.length,
      covers_7d: null,
      covers_30d: null,
    },
    segments,
    ...overrides,
  };
}

const RETAIL_INSTRUMENT = { reference_type: "retail_sell", evidence_type: "listing" };
const FLOOR_INSTRUMENT = { reference_type: "listing_floor", evidence_type: "listing" };

/** Market Index + Yuyu-Tei + SNKRDUNK, all with movement. */
function threePlatformSeries(window: PrintSeriesWindow = "30d"): PrintSeriesHistory {
  return {
    card_print_id: 11,
    window,
    window_start: "2026-08-06T00:00:00Z",
    generated_at: "2026-09-05T00:00:00Z",
    series: [
      seriesEntry({
        key: "market_index",
        kind: "market_index",
        segments: [
          seriesSegment([seriesPoint("2026-09-01", 4100), seriesPoint("2026-09-02", 4150)], {
            index_version: 3,
          }),
        ],
      }),
      seriesEntry({
        key: "source:yuyutei",
        kind: "source",
        source: "yuyutei",
        segments: [
          seriesSegment(
            [
              seriesPoint("2026-09-01", 3980, RETAIL_INSTRUMENT),
              seriesPoint("2026-09-02", 4280, RETAIL_INSTRUMENT),
            ],
            RETAIL_INSTRUMENT,
          ),
        ],
      }),
      seriesEntry({
        key: "source:snkrdunk",
        kind: "source",
        source: "snkrdunk",
        segments: [
          seriesSegment(
            [
              seriesPoint("2026-09-01", 4300, FLOOR_INSTRUMENT),
              seriesPoint("2026-09-02", 4020, FLOOR_INSTRUMENT),
            ],
            FLOOR_INSTRUMENT,
          ),
        ],
      }),
    ],
  };
}

function renderChart(
  series: PrintSeriesHistory | null,
  overrides: {
    window?: PrintSeriesWindow;
    onWindowChange?: (window: PrintSeriesWindow) => void;
    seriesLoading?: boolean;
    prices?: PrintPriceHistoryPayload;
  } = {},
) {
  return render(
    <PrintPriceHistory
      view={overrides.prices ? buildPriceHistoryView(overrides.prices, 11) : null}
      series={series}
      seriesLoading={overrides.seriesLoading ?? false}
      window={overrides.window ?? "30d"}
      onWindowChange={overrides.onWindowChange ?? (() => {})}
    />,
  );
}

function chipNames(): string[] {
  return Array.from(
    screen.getByTestId("price-history-series-selector").querySelectorAll("button"),
  ).map((button) => button.textContent ?? "");
}

describe("series selector", () => {
  it("offers Market Index and every platform with history for this print", () => {
    renderChart(threePlatformSeries());

    // Platform AND instrument: a shop's asking price and a marketplace's
    // cheapest open listing are different claims, and a legend naming only
    // the platforms would put them on one chart as if they were the same
    // measurement. Market Index carries no suffix - it is not quoted in an
    // instrument.
    expect(chipNames()).toEqual([
      "Market Index",
      "Yuyu-Tei · Retail price",
      "SNKRDUNK · Current listing",
    ]);
    for (const name of ["Market Index", "Yuyu-Tei · Retail price", "SNKRDUNK · Current listing"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
    }
    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
  });

  it("offers a platform this build has never heard of, with no code for it", () => {
    const payload = threePlatformSeries();
    payload.series.push(
      seriesEntry({
        key: "source:cardrush",
        kind: "source",
        source: "cardrush",
        segments: [
          seriesSegment(
            [
              seriesPoint("2026-09-01", 5100, { reference_type: "auction_high" }),
              seriesPoint("2026-09-02", 5300, { reference_type: "auction_high" }),
            ],
            { reference_type: "auction_high", evidence_type: "transaction" },
          ),
        ],
      }),
    );
    renderChart(payload);

    expect(chipNames()).toContain("cardrush · Auction high");
    expect(screen.getByRole("button", { name: "cardrush · Auction high" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("removes a platform from the chart when it is deselected, and brings it back", () => {
    renderChart(threePlatformSeries());
    const snkrdunk = screen.getByRole("button", { name: "SNKRDUNK · Current listing" });

    fireEvent.click(snkrdunk);
    expect(snkrdunk).toHaveAttribute("aria-pressed", "false");
    // The other two are untouched, and the chart is still drawn.
    expect(screen.getByRole("button", { name: "Yuyu-Tei · Retail price" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();

    fireEvent.click(snkrdunk);
    expect(snkrdunk).toHaveAttribute("aria-pressed", "true");
  });

  it("says so plainly when the reader turns every platform off", () => {
    renderChart(threePlatformSeries());
    for (const name of ["Market Index", "Yuyu-Tei · Retail price", "SNKRDUNK · Current listing"]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }

    expect(screen.queryByTestId("price-history-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("price-history-empty")).toHaveTextContent(
      "Select a platform to chart.",
    );
  });

  it("offers no chip for a source that has no history for this print", () => {
    const payload = threePlatformSeries();
    payload.series.push(
      seriesEntry({
        key: "source:cardmarket",
        kind: "source",
        source: "cardmarket",
        available: false,
        unavailable_reason: "source_not_configured",
      }),
      seriesEntry({
        key: "source:mercari",
        kind: "source",
        source: "mercari",
        available: false,
        unavailable_reason: "no_history_in_window",
      }),
    );
    renderChart(payload);

    // Both are real answers, and neither gives the reader anything to toggle.
    // A dead control beside three live ones reads as a broken platform.
    expect(chipNames()).toEqual([
      "Market Index",
      "Yuyu-Tei · Retail price",
      "SNKRDUNK · Current listing",
    ]);
  });
});

describe("time window control", () => {
  it("offers 7D, 30D and All - and never 90D", () => {
    renderChart(threePlatformSeries());
    const control = screen.getByTestId("price-history-window");

    expect(Array.from(control.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
      "7D",
      "30D",
      "All",
    ]);
    expect(control.textContent).not.toMatch(/90/);
  });

  it("defaults to 30D", () => {
    renderChart(threePlatformSeries());
    expect(screen.getByRole("button", { name: "30D" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps the chart on screen while the next window loads", () => {
    // Swapping the plot for a placeholder unmounts Recharts' responsive
    // container, which repaints empty on remount - so the section visibly
    // collapses and re-inflates under a control meant to read as a filter.
    renderChart(threePlatformSeries(), { window: "7d", seriesLoading: true });

    const chart = screen.getByTestId("price-history-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("aria-busy", "true");
    // ...and the control already shows what was asked for.
    expect(screen.getByRole("button", { name: "7D" })).toHaveAttribute("aria-pressed", "true");
  });

  it("asks the caller to re-request rather than filtering what it already has", () => {
    const onWindowChange = vi.fn();
    renderChart(threePlatformSeries(), { onWindowChange });

    fireEvent.click(screen.getByRole("button", { name: "7D" }));
    expect(onWindowChange).toHaveBeenCalledWith("7d");

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(onWindowChange).toHaveBeenCalledWith("all");
  });
});

describe("empty and thin history", () => {
  it("shows a one-point series without inventing a line", () => {
    const payload = threePlatformSeries();
    payload.series = [
      seriesEntry({
        key: "source:yuyutei",
        kind: "source",
        source: "yuyutei",
        segments: [
          seriesSegment([seriesPoint("2026-09-02", 3980, RETAIL_INSTRUMENT)], RETAIL_INSTRUMENT),
        ],
      }),
    ];
    renderChart(payload);

    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("price-history-empty")).not.toBeInTheDocument();
  });

  it("blames the window, not the card, when 7D holds nothing", () => {
    // Observations older than the window: the print HAS history and the rows
    // beneath prove it, so the chart's emptiness is a fact about 7D.
    renderChart(
      {
        card_print_id: 11,
        window: "7d",
        window_start: "2026-08-29T00:00:00Z",
        generated_at: "2026-09-05T00:00:00Z",
        series: [
          seriesEntry({ key: "market_index", kind: "market_index" }),
          seriesEntry({
            key: "source:yuyutei",
            kind: "source",
            source: "yuyutei",
            available: false,
            unavailable_reason: "no_history_in_window",
          }),
        ],
      },
      {
        window: "7d",
        prices: {
          card_print_id: 11,
          observations: [
            observation({ observed_at: "2026-07-01T00:00:00Z", price_jpy: 7980 }),
            observation({ observed_at: "2026-07-02T00:00:00Z", price_jpy: 8180 }),
          ],
          series: [],
        },
      },
    );

    expect(screen.getByTestId("price-history-empty")).toHaveTextContent(
      "No recorded price history in this window.",
    );
    // The evidence rows stay: the section is not hidden because one window is
    // empty.
    expect(screen.getByText("￥8,180")).toBeInTheDocument();
    expect(screen.queryByTestId("price-history-series-selector")).not.toBeInTheDocument();
  });

  it("says a wholly constrained platform has nothing to plot, without hiding it", () => {
    renderChart({
      card_print_id: 11,
      window: "30d",
      window_start: "2026-08-06T00:00:00Z",
      generated_at: "2026-09-05T00:00:00Z",
      series: [
        seriesEntry({
          key: "source:snkrdunk",
          kind: "source",
          source: "snkrdunk",
          segments: [
            seriesSegment(
              [
                seriesPoint("2026-09-01", 1000, {
                  ...FLOOR_INSTRUMENT,
                  eligible: false,
                  constraint: "platform_floor",
                }),
                seriesPoint("2026-09-02", 1000, {
                  ...FLOOR_INSTRUMENT,
                  eligible: false,
                  constraint: "platform_floor",
                }),
              ],
              FLOOR_INSTRUMENT,
            ),
          ],
        }),
      ],
    });

    // The platform is still a chip - it reported, and the reader can see that
    // it did - but no ¥1,000 reaches the axis.
    expect(chipNames()).toEqual(["SNKRDUNK · Current listing"]);
    expect(screen.getByTestId("price-history-empty")).toHaveTextContent(
      "No plotted prices for the selected platforms in this window.",
    );
  });

  it("never lights a chip for a platform that has no line on the plot", () => {
    // print 5's shape: SNKRDUNK quotes only its ¥1,000 platform floor, so it
    // has points but no stroke, while Market Index and Yuyu-Tei plot fine.
    // A plain lit chip would assert a white line that is not there.
    const payload = threePlatformSeries();
    // index 2 IS the SNKRDUNK entry - replacing index 1 would leave two
    // series sharing the key "source:snkrdunk".
    payload.series[2] = seriesEntry({
      key: "source:snkrdunk",
      kind: "source",
      source: "snkrdunk",
      segments: [
        seriesSegment(
          [
            seriesPoint("2026-09-01", 1000, {
              ...FLOOR_INSTRUMENT,
              eligible: false,
              constraint: "platform_floor",
            }),
            seriesPoint("2026-09-02", 1000, {
              ...FLOOR_INSTRUMENT,
              eligible: false,
              constraint: "platform_floor",
            }),
          ],
          FLOOR_INSTRUMENT,
        ),
      ],
    });
    const { container } = renderChart(payload);

    // The chart still draws, so this is not the empty state - the chip is
    // lit beside a plot that contains no SNKRDUNK.
    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
    // The chip announces it rather than silently promising a line.
    expect(
      screen.getByRole("button", {
        name: "SNKRDUNK · Current listing — nothing to plot in this window",
      }),
    ).toBeInTheDocument();
    // And the chart says why, naming the platform.
    expect(container.textContent).toMatch(
      /SNKRDUNK · Current listing has no market price to plot in this window/,
    );
  });

  it("says nothing about unplotted platforms when every selected one draws", () => {
    const { container } = renderChart(threePlatformSeries());
    expect(container.textContent).not.toMatch(/no market price to plot/);
    expect(
      screen.getByRole("button", { name: "SNKRDUNK · Current listing" }),
    ).toBeInTheDocument();
  });

  it("renders no section at all when neither payload has anything", () => {
    const { container } = renderChart(null);
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps the section alive on the chart alone when /prices gave nothing", () => {
    // Archived index history with no surviving observations: a section with a
    // chart and no rows beats no section at all.
    renderChart(threePlatformSeries());
    expect(screen.getByRole("heading", { name: "Price history" })).toBeInTheDocument();
    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
  });
});

describe("what the section never says", () => {
  it("shows ONE vocabulary for a source across chip, chart note, tooltip and row", () => {
    // The regression this pins: the chip said "SNKRDUNK · Current listing"
    // while the evidence row beneath it said "SNKRDUNK listing floor" - two
    // names for one reading, 150px apart, in one section.
    const { container } = renderChart(threePlatformSeries(), {
      prices: {
        card_print_id: 11,
        observations: [
          observation({ observed_at: "2026-09-01T00:00:00Z", price_jpy: 3980 }),
          observation({ observed_at: "2026-09-02T00:00:00Z", price_jpy: 4280 }),
          observation({
            observed_at: "2026-09-02T00:00:00Z",
            source: "snkrdunk",
            source_id: 2,
            price_type: "floor",
            reference_type: "listing_floor",
            price_jpy: 4020,
          }),
        ],
        series: [],
      },
    });

    const text = container.textContent ?? "";
    // No stored price_type token reaches the collector anywhere in the section.
    expect(text).not.toMatch(/listing floor/i);
    expect(text).not.toMatch(/\bYuyu-Tei sell\b/);
    expect(text).not.toMatch(/\bmedian sold\b/i);
    // And the one vocabulary appears on both the chip and the row.
    expect(screen.getAllByText("SNKRDUNK · Current listing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Yuyu-Tei · Retail price").length).toBeGreaterThan(0);
  });

  it("carries no confidence, reliability or agreement wording", () => {
    const { container } = renderChart(threePlatformSeries());
    expect(container.textContent).not.toMatch(/confidence|reliab|agreement|accura|score/i);
  });

  it("carries no stored price_type vocabulary in the chart controls", () => {
    const selector = renderChart(threePlatformSeries())
      .container.querySelector('[data-testid="price-history-series-selector"]')!;
    // "floor" and "sell" are collector-side storage names the server withholds
    // on purpose - a chip must never be labelled with one.
    expect(selector.textContent).not.toMatch(/\bfloor\b|\bsell\b/i);
  });

  it("explains a break without turning it into an alarm", () => {
    const payload = threePlatformSeries();
    payload.series[0] = seriesEntry({
      key: "market_index",
      kind: "market_index",
      segments: [
        seriesSegment([seriesPoint("2026-08-30", 3900), seriesPoint("2026-08-31", 3950)], {
          index_version: 2,
        }),
        seriesSegment([seriesPoint("2026-09-01", 4400), seriesPoint("2026-09-02", 4450)], {
          index_version: 3,
        }),
      ],
      breaks: [
        {
          at: "2026-09-01T20:00:00Z",
          reason: "index_version_change",
          from_index_version: 2,
          to_index_version: 3,
        },
      ],
    });
    const { container } = renderChart(payload);

    // NAMES THE SERIES THAT BROKE. An unqualified "lines are not joined
    // across them" is falsifiable on screen: a platform that did not break
    // runs straight through a mark belonging to one that did.
    expect(
      screen.getByText(
        /Dashed marks show where the measurement changed for Market Index\. Its line is not joined across them\./,
      ),
    ).toBeInTheDocument();
    // Neutral: no warning, no error, no version number pushed at the reader.
    expect(container.textContent).not.toMatch(/warning|error|invalid|v2|v3/i);
  });

  it("never claims a platform's line is unbroken when only the index broke", () => {
    // Yuyu-Tei has no break here. The caption must not promise anything about
    // the Yuyu line, whose stroke legitimately crosses the index's mark.
    const payload = threePlatformSeries();
    payload.series[0] = seriesEntry({
      key: "market_index",
      kind: "market_index",
      segments: [
        seriesSegment([seriesPoint("2026-08-30", 3900)], { index_version: 2 }),
        seriesSegment([seriesPoint("2026-09-01", 4400)], { index_version: 3 }),
      ],
      breaks: [{ at: "2026-09-01T20:00:00Z", reason: "index_version_change" }],
    });
    const { container } = renderChart(payload);

    const caption = container.textContent ?? "";
    expect(caption).toMatch(/changed for Market Index/);
    // The sentence is scoped to the index alone - it says nothing about
    // Yuyu-Tei or SNKRDUNK, which did not break.
    expect(caption).not.toMatch(/Lines are not joined across them/);
  });

  it("says nothing about breaks at all when no series broke", () => {
    const payload = threePlatformSeries();
    for (const entry of payload.series) entry.breaks = [];
    const { container } = renderChart(payload);
    expect(container.textContent).not.toMatch(/Dashed marks/);
  });
});
