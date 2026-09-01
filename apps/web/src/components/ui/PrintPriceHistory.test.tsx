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

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PrintPriceHistory, PrintPriceHistorySection } from "./PrintPriceHistory";
import { buildPriceHistoryView } from "@/lib/printPriceHistory";
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
    ...overrides,
  };
}

function renderHistory(payload: PrintPriceHistoryPayload, cardPrintId = 11) {
  return render(<PrintPriceHistory view={buildPriceHistoryView(payload, cardPrintId)} />);
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
    expect(screen.getAllByText("Yuyu-Tei sell").length).toBeGreaterThan(0);
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
          price_jpy: 1000,
          constraint: "platform_floor",
          eligible: false,
          ineligible_reason: "platform_floor",
        }),
      ],
      series: [],
    });

    expect(screen.getByText("SNKRDUNK listing floor")).toBeInTheDocument();
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

  it("renders a chart and a legend once a series has movement across dates", () => {
    renderHistory({
      card_print_id: 11,
      observations: [
        observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 7980 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 9980 }),
      ],
      series: [],
    });

    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
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
          price_jpy: 1000,
          constraint: "platform_floor",
          eligible: false,
          ineligible_reason: "platform_floor",
        }),
      ],
      series: [],
    });

    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
    expect(screen.getByText(/Not treated as a market price/)).toBeInTheDocument();
    // The constrained source is absent from the chart legend, which lists only
    // the series that are actually stroked.
    expect(screen.getAllByText("SNKRDUNK listing floor")).toHaveLength(1);
    expect(screen.getAllByText("Yuyu-Tei sell")).toHaveLength(2);
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
    const { container } = render(<PrintPriceHistorySection status="loading" view={null} />);

    // Queried by text, not by role: the placeholder is aria-hidden on purpose,
    // so a screen reader is never handed an empty skeleton to announce.
    expect(screen.getByText("Price history")).toBeInTheDocument();
    expect(container.querySelector("section")).toHaveAttribute("aria-hidden", "true");
    // Mute: it claims something is coming, and nothing about what.
    expect(container.textContent).not.toMatch(/￥|%|More history/);
  });

  it("renders nothing once history is known to be unavailable", () => {
    const { container } = render(<PrintPriceHistorySection status="unavailable" view={null} />);
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
      />,
    );

    // The span is what this section knows that the Market Index source panel
    // above it does not - so the row is not a second copy of that panel.
    expect(screen.getByText(/2 readings, Aug 20, 2026 – Aug 31, 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Not treated as a market price/)).toBeInTheDocument();
  });
});
