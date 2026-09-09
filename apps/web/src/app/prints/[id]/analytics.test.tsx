/** The exact-print analytics band: what it asks the server for, what it
 * refuses to ask for, and what it renders from the answer.
 *
 * THE ONE THING EVERY TEST HERE IS REALLY ABOUT: no figure on this band is
 * computed in the browser. The headline is read field-by-field off
 * `analytics.headline`, the timeframe map is read off `analytics.windows`, and
 * the opening view is read off `analytics.default_window`. So the fixtures
 * below deliberately contain values that a client recomputing from the chart's
 * points would get WRONG - a high that is not the largest plotted point, a
 * default window that is not the widest available one - and the assertions
 * check that the server's answer is what reaches the screen.
 *
 * Recharts measures 0 in jsdom and draws no path (see PrintPriceHistory.test),
 * so the chart is asserted through its container, its chips and its captions
 * rather than its geometry.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/prints/1",
  useSearchParams: () => new URLSearchParams(""),
  useParams: () => ({ id: "1" }),
}));

const { fetchPrint, fetchPrintPrices } = vi.hoisted(() => ({
  fetchPrint: vi.fn(),
  fetchPrintPrices: vi.fn(),
}));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrint, fetchPrintPrices };
});

const { fetchPrintAnalytics } = vi.hoisted(() => ({ fetchPrintAnalytics: vi.fn() }));
vi.mock("@/lib/printAnalytics", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/printAnalytics")>("@/lib/printAnalytics");
  return { ...actual, fetchPrintAnalytics };
});

import type { PrintDetail } from "@/lib/prints";
import type {
  PrintAnalytics,
  PrintAnalyticsHeadline,
  PrintAnalyticsWindowRow,
} from "@/lib/printAnalytics";
import type { PrintSeries, PrintSeriesPoint } from "@/lib/printSeries";

import PrintDetailPage from "./page";

const { downloadPrintChartExport } = vi.hoisted(() => ({
  downloadPrintChartExport:
    vi.fn<(plan: Record<string, unknown>, options?: unknown) => Promise<boolean>>(() =>
      Promise.resolve(true),
    ),
}));
vi.mock("@/lib/printChartExport", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/printChartExport")>("@/lib/printChartExport");
  // Only the browser half is stubbed - jsdom has no 2D context. The PLAN is
  // still built by the real `buildPrintChartExport`, so these assert what the
  // page actually hands to the encoder.
  return { ...actual, downloadPrintChartExport };
});

// --- fixtures ---------------------------------------------------------------

function makeDetail(): PrintDetail {
  return {
    card_print_id: 1,
    canonical_card_id: 9,
    card_code: "OP01-001",
    name_en: "Roronoa Zoro",
    name_jp: null,
    rarity: "L",
    canonical_rarity: "L",
    card_type: "Leader",
    colors: ["Red"],
    language: "ja",
    treatment: null,
    release_product_code: "OP-01",
    original_set_code: "OP-01",
    official_asset_variant: "base",
    artwork_key: null,
    image_url: null,
    display_image: null,
    verification_status: "verified",
    market_index: {
      card_print_id: 1,
      index_version: 3,
      source_semantics_version: 2,
      index_value_jpy: 22900,
      calculation_method: "median_of_sources",
      source_count: 2,
      coverage_status: "full",
      confidence: "high",
      source_price_range: null,
      source_values: [],
      freshest_observation_at: "2026-09-08T20:00:00Z",
    },
    siblings: [],
  } as unknown as PrintDetail;
}

function point(day: string, value: number | null): PrintSeriesPoint {
  return {
    t: `${day}T20:00:00Z`,
    day,
    value_jpy: value,
    reference_type: null,
    evidence_type: null,
    eligible: null,
    constraint: null,
    ineligible_reason: null,
    sample_size: null,
    observations_in_day: null,
    index_version: 3,
    source_semantics_version: 2,
    source_count: 1,
    coverage_status: "full",
    source_price_range_low_jpy: null,
    source_price_range_high_jpy: null,
  } as unknown as PrintSeriesPoint;
}

function series(key: string, source: string | null, days: string[]): PrintSeries {
  return {
    key,
    kind: source ? "source" : "market_index",
    source,
    role: "primary",
    available: true,
    unavailable_reason: null,
    segments: [
      {
        reference_type: source ? "retail_sell" : null,
        evidence_type: source ? "listing" : null,
        index_version: 3,
        source_semantics_version: 2,
        points: days.map((day, i) => point(day, 20000 + i * 100)),
      },
    ],
    breaks: [],
    coverage: {
      earliest: `${days[0]}T20:00:00Z`,
      latest: `${days[days.length - 1]}T20:00:00Z`,
      distinct_days: days.length,
      point_count: days.length,
      covers_7d: true,
      covers_30d: false,
    },
  } as unknown as PrintSeries;
}

function windows(overrides: Partial<Record<string, boolean>> = {}): PrintAnalyticsWindowRow[] {
  // The order IS the contract: the server publishes it, and a client that
  // re-sorted would be re-deciding a server rule.
  const spec: [string, number | null][] = [
    ["2w", 14],
    ["1m", 30],
    ["3m", 90],
    ["6m", 180],
    ["1y", 365],
    ["2y", 730],
    ["all", null],
  ];
  return spec.map(([token, required]) => ({
    token,
    available: overrides[token] ?? (token === "2w" || token === "1m" || token === "all"),
    covered_days: 33,
    required_days: required,
  }));
}

function headline(overrides: Partial<PrintAnalyticsHeadline> = {}): PrintAnalyticsHeadline {
  return {
    current_value_jpy: 22900,
    current_as_of: "2026-09-08",
    starting_value_jpy: 27400,
    starting_as_of: "2026-08-21",
    // Deliberately NOT the largest number among the plotted points below: a
    // client recomputing the high from the chart would print 20200.
    high_value_jpy: 27400,
    high_as_of: "2026-08-21",
    low_value_jpy: 22650,
    low_as_of: "2026-09-01",
    change: null,
    change_unavailable_reason: "index_version_change",
    observed_days: 19,
    coverage_status: "full",
    ...overrides,
  };
}

function analytics(overrides: Partial<PrintAnalytics> = {}): PrintAnalytics {
  return {
    card_print_id: 1,
    requested_window: "all",
    window_start: null,
    // The 3B-1 pairing: source history makes 2W and 1M selectable, while the
    // Market Index's own 19 days keep the opening view at `all`.
    default_window: "all",
    generated_at: "2026-09-09T08:00:00Z",
    windows: windows(),
    headline: headline(),
    series: [
      series("market_index", null, ["2026-09-06", "2026-09-07", "2026-09-08"]),
      series("source:yuyutei", "yuyutei", ["2026-09-06", "2026-09-07", "2026-09-08"]),
      series("source:snkrdunk", "snkrdunk", ["2026-09-06", "2026-09-07", "2026-09-08"]),
    ],
    ...overrides,
  };
}

async function renderPage() {
  render(<PrintDetailPage />);
  await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });
  await screen.findByTestId("print-analytics-current");
}

function windowButtons(): HTMLButtonElement[] {
  return Array.from(
    screen.getByTestId("print-analytics-window").querySelectorAll("button"),
  ) as HTMLButtonElement[];
}

beforeEach(() => {
  fetchPrint.mockResolvedValue(makeDetail());
  fetchPrintPrices.mockResolvedValue({ card_print_id: 1, observations: [], series: [] });
  fetchPrintAnalytics.mockResolvedValue(analytics());
});

afterEach(() => {
  vi.clearAllMocks();
});

// --- the PNG export ---------------------------------------------------------

describe("downloading the chart", () => {
  it("issues no request at all", async () => {
    await renderPage();
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("print-export"));

    await waitFor(() => expect(downloadPrintChartExport).toHaveBeenCalledTimes(1));
    // The plan is built from the response the page is already holding, so
    // saving a picture of it cannot cost a round trip.
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);
    expect(fetchPrint).toHaveBeenCalledTimes(1);
    expect(fetchPrintPrices).toHaveBeenCalledTimes(1);
  });

  it("exports the window currently on screen, not the default", async () => {
    fetchPrintAnalytics
      .mockResolvedValueOnce(analytics())
      .mockResolvedValueOnce(analytics({ requested_window: "2w" }));
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "2W" }));
    await waitFor(() => expect(fetchPrintAnalytics).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByTestId("print-export"));
    await waitFor(() => expect(downloadPrintChartExport).toHaveBeenCalled());

    const plan = downloadPrintChartExport.mock.calls[0][0] as unknown as {
      windowToken: string;
      filename: string;
    };
    expect(plan.windowToken).toBe("2w");
    expect(plan.filename).toContain("-2w-");
  });

  it("carries the exact print's identity and the series on screen", async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("print-export"));
    await waitFor(() => expect(downloadPrintChartExport).toHaveBeenCalled());

    const plan = downloadPrintChartExport.mock.calls[0][0] as unknown as {
      title: string;
      subtitle: string;
      printRef: string;
      series: { label: string }[];
      current: string | null;
    };
    expect(plan.title).toBe("Roronoa Zoro");
    expect(plan.subtitle).toContain("OP01-001");
    expect(plan.printRef).toBe("#1");
    expect(plan.series.map((s) => s.label)).toEqual(
      expect.arrayContaining(["Market Index", "Yuyu-Tei", "SNKRDUNK"]),
    );
    // The headline in the file is the one on the screen.
    expect(plan.current).toBe("￥22,900");
  });

  it("names the card and the timeframe in its accessible name", async () => {
    await renderPage();

    const button = screen.getByTestId("print-export");
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("aria-label")).toContain("Roronoa Zoro");
    expect(button.getAttribute("aria-label")).toContain("OP01-001");
    expect(button.getAttribute("aria-label")).toContain("All");
  });

  it("stays quiet and does nothing when there is nothing chartable", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({
        series: [],
        headline: headline({ current_value_jpy: null, observed_days: 0 }),
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByTestId("print-analytics");

    const button = await screen.findByTestId("print-export");
    expect(button).toHaveAttribute("aria-disabled", "true");
    // Focusable, so the reason in the accessible name is reachable.
    expect(button).not.toBeDisabled();

    fireEvent.click(button);
    expect(downloadPrintChartExport).not.toHaveBeenCalled();
  });

  it("says so quietly instead of crashing when the encode fails", async () => {
    downloadPrintChartExport.mockResolvedValueOnce(false);
    await renderPage();

    fireEvent.click(screen.getByTestId("print-export"));

    expect(await screen.findByTestId("print-export-error")).toHaveTextContent(
      /could not be saved/i,
    );
    // The page is still there.
    expect(screen.getByTestId("print-analytics-current")).toBeInTheDocument();
  });

  it("leaves the on-screen timeframe controls untouched", async () => {
    await renderPage();
    const before = windowButtons().map((b) => [b.textContent, b.getAttribute("aria-pressed")]);

    fireEvent.click(screen.getByTestId("print-export"));
    await waitFor(() => expect(downloadPrintChartExport).toHaveBeenCalled());

    expect(windowButtons().map((b) => [b.textContent, b.getAttribute("aria-pressed")])).toEqual(
      before,
    );
  });

  it("draws the brand mark inside the plot, behind the data", async () => {
    await renderPage();

    const watermark = screen.getByTestId("print-chart-watermark");
    expect(watermark).toBeInTheDocument();
    // Decoration: no chart meaning, so a screen reader must not announce it.
    expect(watermark).toHaveAttribute("aria-hidden", "true");
    // Behind the lines and out of the tooltip's hit-testing.
    expect(watermark.className).toContain("z-0");
    expect(watermark.className).toContain("pointer-events-none");
    // Inside the plot container, not a second logo beside it.
    expect(screen.getByTestId("price-history-chart").contains(watermark)).toBe(true);
  });
});

// --- the server decides the opening view ------------------------------------

describe("the server's default window", () => {
  it("opens by asking for no window at all", async () => {
    await renderPage();

    // The ONLY way `default_window` can be the server's answer rather than
    // something this page believes about it.
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);
    expect(fetchPrintAnalytics).toHaveBeenCalledWith("1", undefined);
  });

  it("presses `all` even though 2W and 1M are available", async () => {
    // THE 3B-1 PROOF, on screen. `windows[].available` spans every series, so
    // a month of Yuyu-Tei history makes 1M selectable; `default_window` spans
    // the Market Index alone, which has 19 days. The two disagreeing is the
    // intended behaviour, and the page must not "correct" it by pressing the
    // widest available token.
    await renderPage();

    const pressed = windowButtons().filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe("All");
    expect(screen.getByRole("button", { name: "1M" })).toHaveAttribute("aria-pressed", "false");
  });

  it("follows a default the client would never have guessed", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({ requested_window: "3m", default_window: "3m", windows: windows({ "3m": true }) }),
    );
    await renderPage();

    const pressed = windowButtons().filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe("3M");
  });
});

// --- the control ------------------------------------------------------------

describe("the timeframe control", () => {
  it("renders all seven tokens in the server's order", async () => {
    await renderPage();

    expect(windowButtons().map((b) => b.textContent)).toEqual([
      "2W",
      "1M",
      "3M",
      "6M",
      "1Y",
      "2Y",
      "All",
    ]);
  });

  it("issues no request at all for an unavailable window", async () => {
    await renderPage();
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /^3M/ }));
    fireEvent.click(screen.getByRole("button", { name: /^1Y/ }));
    fireEvent.click(screen.getByRole("button", { name: /^2Y/ }));

    // The server already said it cannot answer these spans. A round trip whose
    // answer is known before it is sent is not a loading state, it is waste.
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);
    // ...and the pressed token did not move.
    const pressed = windowButtons().filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed.map((b) => b.textContent)).toEqual(["All"]);
  });

  it("keeps an unavailable window visible, focusable and explained", async () => {
    await renderPage();

    const threeMonth = screen.getByRole("button", { name: /^3M/ });
    // Visible, not removed: hiding it would silently shrink the grammar the
    // server published.
    expect(threeMonth).toBeInTheDocument();
    expect(threeMonth).toHaveAttribute("aria-disabled", "true");
    // Never natively disabled - that drops it out of the tab order and takes
    // the explanation with it.
    expect(threeMonth).not.toBeDisabled();
    // The server's own two numbers, reachable by keyboard and screen reader
    // rather than by hovering.
    expect(threeMonth.getAttribute("aria-label")).toContain("33 days");
    expect(threeMonth.getAttribute("aria-label")).toContain("needs 90");
    expect(threeMonth).toHaveAttribute("title", expect.stringContaining("needs 90"));
  });

  it("issues exactly one request for an available window, carrying that token", async () => {
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "1M" }));

    await waitFor(() => expect(fetchPrintAnalytics).toHaveBeenCalledTimes(2));
    expect(fetchPrintAnalytics).toHaveBeenLastCalledWith("1", "1m");
  });

  it("keeps exactly one control selected after a change", async () => {
    fetchPrintAnalytics
      .mockResolvedValueOnce(analytics())
      .mockResolvedValueOnce(analytics({ requested_window: "1m" }));
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "1M" }));

    await waitFor(() => {
      const pressed = windowButtons().filter((b) => b.getAttribute("aria-pressed") === "true");
      expect(pressed.map((b) => b.textContent)).toEqual(["1M"]);
    });
  });
});

// --- the headline -----------------------------------------------------------

describe("the archived headline", () => {
  it("renders every figure from the server's headline, not from the chart", async () => {
    await renderPage();

    const band = screen.getByTestId("print-analytics");
    expect(screen.getByTestId("print-analytics-current")).toHaveTextContent("￥22,900");
    expect(within(band).getByText("As of Sep 8, 2026")).toBeInTheDocument();

    const stats = screen.getByTestId("print-analytics-stats");
    expect(stats).toHaveTextContent("￥27,400");
    expect(stats).toHaveTextContent("￥22,650");
    expect(stats).toHaveTextContent("19");

    // The plotted points top out at ￥20,200. A client deriving the high from
    // them would print that; the server's 27,400 is what must be on screen.
    expect(stats).not.toHaveTextContent("￥20,200");
  });

  it("replaces the headline from the window's own response", async () => {
    fetchPrintAnalytics.mockResolvedValueOnce(analytics()).mockResolvedValueOnce(
      analytics({
        requested_window: "1m",
        headline: headline({
          current_value_jpy: 24900,
          current_as_of: "2026-09-07",
          high_value_jpy: 31000,
          high_as_of: "2026-08-30",
          observed_days: 12,
        }),
      }),
    );
    await renderPage();
    expect(screen.getByTestId("print-analytics-current")).toHaveTextContent("￥22,900");

    fireEvent.click(screen.getByRole("button", { name: "1M" }));

    await waitFor(() =>
      expect(screen.getByTestId("print-analytics-current")).toHaveTextContent("￥24,900"),
    );
    expect(screen.getByTestId("print-analytics-stats")).toHaveTextContent("￥31,000");
    expect(screen.getByTestId("print-analytics-stats")).toHaveTextContent("12");
  });

  it("names the server's reason instead of computing a change", async () => {
    await renderPage();

    const line = screen.getByTestId("print-analytics-change-unavailable");
    expect(line).toHaveTextContent(/changed how the Market Index is calculated/i);
    // No figure invented in place of the refusal. A first-vs-last subtraction
    // over this window would confidently report a methodology change as a
    // price movement.
    expect(screen.queryByTestId("print-analytics-change")).not.toBeInTheDocument();
    expect(line.textContent).not.toMatch(/%|￥/);
  });

  it("publishes a change exactly as the server signed it", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({
        headline: headline({
          change: {
            absolute_jpy: -4500,
            pct: -16.42,
            from_date: "2026-08-21",
            to_date: "2026-09-08",
            spans_break: false,
          },
          change_unavailable_reason: null,
        }),
      }),
    );
    await renderPage();

    const change = screen.getByTestId("print-analytics-change");
    expect(change).toHaveTextContent("−￥4,500");
    expect(change).toHaveTextContent("16.42%");
    expect(screen.queryByTestId("print-analytics-change-unavailable")).not.toBeInTheDocument();
  });

  it("says a published change still crosses a boundary, when it does", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({
        headline: headline({
          change: {
            absolute_jpy: 1200,
            pct: 5.5,
            from_date: "2026-08-21",
            to_date: "2026-09-08",
            spans_break: true,
          },
          change_unavailable_reason: null,
        }),
      }),
    );
    await renderPage();

    expect(screen.getByTestId("print-analytics-change")).toHaveTextContent(
      /changed how this was measured inside the window/i,
    );
  });

  it("shows no price at all rather than ￥0 when nothing is archived", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({
        headline: headline({
          current_value_jpy: null,
          current_as_of: null,
          starting_value_jpy: null,
          starting_as_of: null,
          high_value_jpy: null,
          high_as_of: null,
          low_value_jpy: null,
          low_as_of: null,
          change_unavailable_reason: "no_archived_value_in_window",
          observed_days: 0,
          coverage_status: null,
        }),
        windows: windows({ "2w": false, "1m": false, all: false }),
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByRole("heading", { name: "Roronoa Zoro", level: 1 });

    const band = await screen.findByTestId("print-analytics");
    expect(within(band).getByText("Index unavailable")).toBeInTheDocument();
    expect(band.textContent).not.toMatch(/￥0\b/);
  });

  it("still renders an inert control when even `all` is unavailable", async () => {
    fetchPrintAnalytics.mockResolvedValue(
      analytics({
        headline: headline({ current_value_jpy: null, observed_days: 0 }),
        windows: windows({ "2w": false, "1m": false, all: false }),
      }),
    );
    render(<PrintDetailPage />);
    await screen.findByTestId("print-analytics");
    await waitFor(() => expect(windowButtons()).toHaveLength(7));
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);

    windowButtons().forEach((button) => fireEvent.click(button));

    // `default_window` is still `all`, and `all` is still unavailable. The
    // control renders and refuses; it does not vanish and does not request.
    expect(fetchPrintAnalytics).toHaveBeenCalledTimes(1);
  });

  it("carries no volume, sample-size or average claim", async () => {
    await renderPage();

    const band = screen.getByTestId("print-analytics");
    // `observed_days` counts days Atlas archived a number. Nothing recorded
    // anywhere in Atlas is a transaction, and there is no average price
    // because the only combination rule the system owns is a same-day median.
    expect(band.textContent).toMatch(/Observed/);
    expect(band.textContent).not.toMatch(/sales|traded|trades|volume|sample|average|mean/i);
  });
});

// --- the chart --------------------------------------------------------------

describe("the chart", () => {
  it("is fed from the analytics response, with its source labels intact", async () => {
    await renderPage();

    expect(screen.getByTestId("price-history-chart")).toBeInTheDocument();
    const chips = screen.getByTestId("price-history-series-selector");
    expect(chips).toHaveTextContent("Market Index");
    expect(chips).toHaveTextContent("Yuyu-Tei");
    expect(chips).toHaveTextContent("SNKRDUNK");
    // The instrument travels with the platform: a shop's asking price and a
    // marketplace's cheapest open listing are different claims about a card.
    expect(chips).toHaveTextContent("Retail price");
  });

  it("keeps the previous plot on screen, dimmed, while the next window loads", async () => {
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "1M" }));

    const chart = screen.getByTestId("price-history-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("aria-busy", "true");
  });

  it("keeps the server's breaks rather than joining across them", async () => {
    const broken = series("market_index", null, ["2026-09-06", "2026-09-07", "2026-09-08"]);
    broken.segments = [
      { ...broken.segments[0], index_version: 2, points: [point("2026-09-06", 20000)] },
      {
        ...broken.segments[0],
        index_version: 3,
        points: [point("2026-09-07", 20100), point("2026-09-08", 20200)],
      },
    ];
    broken.breaks = [
      {
        at: "2026-09-07T20:00:00Z",
        reason: "index_version_change",
        from_index_version: 2,
        to_index_version: 3,
      },
    ] as unknown as PrintSeries["breaks"];
    fetchPrintAnalytics.mockResolvedValue(analytics({ series: [broken] }));
    await renderPage();

    // The caption the chart draws for a real server break, naming the series
    // it belongs to - and stating that the line is NOT joined across it.
    expect(screen.getByTestId("print-analytics")).toHaveTextContent(
      /not joined across them/i,
    );
  });

  it("is the tallest element in the band", async () => {
    await renderPage();

    // Asserted through the class rather than geometry: jsdom lays nothing out,
    // and the point of the tranche is that the plot outweighs the number above
    // it at every width.
    const chart = screen.getByTestId("price-history-chart");
    expect(chart.className).toMatch(/h-\[300px\]/);
    expect(chart.className).toMatch(/lg:h-\[380px\]/);
  });
});

// --- the temporal split -----------------------------------------------------

describe("archived versus live", () => {
  it("never shows an unlabelled second Market Index", async () => {
    await renderPage();

    // One heading, on the archived band. The live figure below it sits on a
    // row that names itself, inside a section that names itself "Live market".
    expect(screen.getAllByRole("heading", { name: "Market Index" })).toHaveLength(1);
    const live = screen.getByTestId("live-market");
    expect(within(live).getByText("Market Index")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Live market" })).toBeInTheDocument();
  });

  it("keeps the archived headline free of any freshness wording", async () => {
    await renderPage();

    // `As of <day>` is provenance for an archived point. The archive is
    // written once a day by design, so its age is the design rather than a
    // fault to flag - "updated N ago" would misread one as the other.
    const band = screen.getByTestId("print-analytics");
    expect(within(band).getByText("As of Sep 8, 2026")).toBeInTheDocument();
    expect(band.textContent).not.toMatch(/updated|ago|stale/i);
  });

  it("shows the archived figure even when the live one differs", async () => {
    // They agree most days and are not required to: the archive is written
    // once daily, so a source that moves this morning shows up live first.
    const detail = makeDetail();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (detail.market_index as any).index_value_jpy = 25500;
    fetchPrint.mockResolvedValue(detail);
    await renderPage();

    expect(screen.getByTestId("print-analytics-current")).toHaveTextContent("￥22,900");
    expect(within(screen.getByTestId("live-market")).getByText("￥25,500")).toBeInTheDocument();
  });
});
