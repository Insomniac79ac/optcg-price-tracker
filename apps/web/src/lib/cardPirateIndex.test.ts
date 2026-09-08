/** Where the index chart's geometry is actually decided.
 *
 * Recharts inside a ResponsiveContainer measures 0 in jsdom and draws no path,
 * so the invariants that matter most - that no point is invented, that a
 * multi-day gap is never stroked as a daily line, and that a flat index is not
 * cosmetically amplified - cannot be asserted through the DOM. They are
 * decided here, by `splitRuns` and `indexDomain`, and asserted here. The same
 * division the print page's chart already keeps between
 * PrintPriceHistory.test.tsx and lib/printSeries.test.ts.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, apiGet };
});

import {
  INDEX_WINDOWS,
  INDEX_WINDOW_LABEL,
  fetchIndexDefault,
  formatAbsoluteChange,
  formatPctChange,
  indexDomain,
  isIndexWindow,
  isSnapshotGap,
  pressedWindow,
  splitRuns,
  windowLabel,
  windowProse,
  type IndexBreak,
  type IndexPoint,
  type IndexSeries,
  type IndexWindowRow,
} from "./cardPirateIndex";

beforeEach(() => {
  // The call log is asserted on directly below, so it has to start empty in
  // every test rather than accumulating across the file.
  apiGet.mockReset();
});

function point(partial: Partial<IndexPoint> & { date: string; value: string }): IndexPoint {
  return {
    is_base: false,
    prior_point_date: null,
    step_days: 1,
    chain_link_log_return: null,
    constituent_count: 296,
    eligible_print_count: 305,
    movers_up: 0,
    movers_down: 0,
    movers_flat: 296,
    capped_count: 0,
    ...partial,
  };
}

function series(partial: Partial<IndexSeries> = {}): IndexSeries {
  return {
    scope_kind: "overall",
    scope_key: "",
    methodology_version: 1,
    index_version: 3,
    source_semantics_version: 2,
    requested_window: "all",
    window_start: null,
    available_from: "2026-09-03",
    available_to: "2026-09-07",
    covers_requested_window: true,
    points: [],
    starting_value: "1000.0000",
    current_value: "1000.1065",
    low_value: "1000.0000",
    high_value: "1000.9577",
    change: null,
    change_unavailable_reason: null,
    windows: WINDOWS,
    default_window: "all",
    breaks: [],
    ...partial,
  };
}

function windowRow(
  token: string,
  available: boolean,
  covered_days = 5,
  required_days: number | null = null,
): IndexWindowRow {
  return { token, available, covered_days, required_days };
}

/** Staging's real window map today: five days of archive, so only `all` is
 * spanned. */
const WINDOWS: IndexWindowRow[] = [
  windowRow("2w", false, 5, 14),
  windowRow("1m", false, 5, 30),
  windowRow("3m", false, 5, 90),
  windowRow("6m", false, 5, 180),
  windowRow("1y", false, 5, 365),
  windowRow("2y", false, 5, 730),
  windowRow("all", true, 5, null),
];

function breakEntry(partial: Partial<IndexBreak> & { at: string; reason: string }): IndexBreak {
  return {
    from_methodology_version: null,
    to_methodology_version: null,
    from_index_version: null,
    to_index_version: null,
    from_source_semantics_version: null,
    to_source_semantics_version: null,
    carried: null,
    carried_level: null,
    carried_from_point_date: null,
    prior_point_date: null,
    step_days: null,
    ...partial,
  };
}

// --- the published grammar --------------------------------------------------

describe("the window grammar is the API's", () => {
  it("is exactly the seven tokens the endpoint accepts", () => {
    expect([...INDEX_WINDOWS]).toEqual(["2w", "1m", "3m", "6m", "1y", "2y", "all"]);
  });

  it("labels every token, and labels nothing else", () => {
    expect(Object.keys(INDEX_WINDOW_LABEL).sort()).toEqual([...INDEX_WINDOWS].sort());
  });

  it("rejects a token outside the grammar", () => {
    // The print page's own windows are NOT this endpoint's; sending one would
    // earn a 400 that names the grammar back.
    expect(isIndexWindow("7d")).toBe(false);
    expect(isIndexWindow("30d")).toBe(false);
    expect(isIndexWindow("90d")).toBe(false);
    expect(isIndexWindow("all")).toBe(true);
  });
});

// --- the section 13.1 ladder ------------------------------------------------

describe("the opening request names no window at all", () => {
  it("sends GET /analytics/index with no params", async () => {
    // The absence of a token IS the request for the default. A client that
    // named one would be re-owning section 13.1's rule, which is what
    // TASK INDEX 2A-C removed along with `BOOTSTRAP_WINDOW`.
    apiGet.mockResolvedValueOnce(series({ requested_window: "all" }));
    await fetchIndexDefault();
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith("/analytics/index");
  });

  it("exports no bootstrap, preferred or fallback window constant", async () => {
    const mod = await vi.importActual<Record<string, unknown>>("./cardPirateIndex");
    for (const name of [
      "BOOTSTRAP_WINDOW",
      "PREFERRED_WINDOW",
      "FALLBACK_WINDOW",
      "DEFAULT_WINDOW",
      "resolveInitialWindow",
      "fetchIndexBootstrap",
      "serverDefaultWindow",
    ]) {
      expect(mod[name]).toBeUndefined();
    }
  });

  it("names no window token anywhere outside the wire vocabulary", async () => {
    // A grep, because the constant could come back as a string literal in a
    // fetch call rather than as an export. `INDEX_WINDOWS` and the label/prose
    // maps are the only places a token may be written down.
    const fs = await import("fs/promises");
    const source = await fs.readFile("src/lib/cardPirateIndex.ts", "utf8");
    const body = source
      .split("\n")
      .filter((line) => !line.trim().startsWith("*") && !line.trim().startsWith("//"))
      .join("\n");
    const afterMaps = body.slice(body.indexOf("export function isIndexWindow"));
    expect(afterMaps).not.toMatch(/["'](2w|1m|3m|6m|1y|2y)["']/);
  });
});

describe("the pressed control comes from the response", () => {
  it("presses the window the payload is about, not the surface default", () => {
    // They differ the moment a reader picks a window: pressing
    // `default_window` would light `3m` while a `1y` chart was on screen.
    expect(
      pressedWindow(series({ requested_window: "1y", default_window: "3m" })),
    ).toBe("1y");
  });

  it("presses the server's default on a first load, because that is what came back", () => {
    expect(
      pressedWindow(series({ requested_window: "all", default_window: "all" })),
    ).toBe("all");
    expect(
      pressedWindow(series({ requested_window: "3m", default_window: "3m" })),
    ).toBe("3m");
  });

  it("refuses a token the server did not publish, rather than pressing nothing", () => {
    const answer = pressedWindow(series({ requested_window: "7d" }));
    expect(answer).toBe("2w");
    expect(WINDOWS.map((row) => row.token)).toContain(answer);
  });

  it("recovers to the server's own first window, not to a hardcoded token", () => {
    expect(
      pressedWindow(
        series({ requested_window: "nope", windows: [windowRow("5y", true, 9, 1825)] }),
      ),
    ).toBe("5y");
  });
});

describe("window tokens are the server's vocabulary", () => {
  it("labels a known token with its frozen display form", () => {
    expect(windowLabel("2w")).toBe("2W");
    expect(windowLabel("all")).toBe("All");
  });

  it("still labels a token this build has never heard of", () => {
    // The server published it, so it is a real window. A control that dropped
    // it would be overriding the authority this tranche moved to the server.
    expect(windowLabel("5y")).toBe("5Y");
  });

  it("has no sentence form for `all` or for an unknown token", () => {
    expect(windowProse("2w")).toBe("two weeks");
    expect(windowProse("all")).toBeNull();
    expect(windowProse("5y")).toBeNull();
  });
});

describe("break reasons are read, not inferred", () => {
  it("separates a cadence gap from a methodology change", () => {
    expect(isSnapshotGap(breakEntry({ at: "2026-09-06", reason: "snapshot_gap" }))).toBe(true);
    expect(
      isSnapshotGap(breakEntry({ at: "2026-09-06", reason: "index_version_change" })),
    ).toBe(false);
  });

  it("treats an unrecognised reason as a boundary, not as nothing", () => {
    // Section 13.4: a marker is never dropped. An unknown reason must not fall
    // through into "no break here".
    expect(isSnapshotGap(breakEntry({ at: "2026-09-06", reason: "future_kind" }))).toBe(false);
  });
});

// --- nothing is invented ----------------------------------------------------

describe("splitRuns never invents, drops or reorders a point", () => {
  const daily = [
    point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
    point({ date: "2026-09-04", value: "1000.8409" }),
    point({ date: "2026-09-05", value: "1000.9577" }),
    point({ date: "2026-09-06", value: "1000.9577" }),
    point({ date: "2026-09-07", value: "1000.1065" }),
  ];

  it("keeps a fully daily series as one unbroken run", () => {
    const runs = splitRuns(daily);
    expect(runs).toHaveLength(1);
    expect(runs[0].gapFrom).toBeNull();
    expect(runs[0].points.map((p) => p.date)).toEqual([
      "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07",
    ]);
  });

  it("breaks the run where step_days says the archive holds nothing", () => {
    const gapped = [
      point({ date: "2026-09-01", value: "1000.0000", is_base: true, step_days: null }),
      point({ date: "2026-09-02", value: "1000.5000" }),
      point({ date: "2026-09-07", value: "1000.1065", step_days: 5 }),
    ];
    const runs = splitRuns(gapped);
    expect(runs).toHaveLength(2);
    expect(runs[0].points.map((p) => p.date)).toEqual(["2026-09-01", "2026-09-02"]);
    expect(runs[1].points.map((p) => p.date)).toEqual(["2026-09-07"]);
    // The dashed connector spans the two REAL endpoints and nothing else.
    expect(runs[1].gapFrom?.date).toBe("2026-09-02");
  });

  it("emits exactly the points it was given, in the order it was given them", () => {
    const gapped = [
      point({ date: "2026-09-01", value: "1000.0000", is_base: true, step_days: null }),
      point({ date: "2026-09-05", value: "1000.5000", step_days: 4 }),
      point({ date: "2026-09-06", value: "1000.7000" }),
      point({ date: "2026-09-11", value: "1000.1065", step_days: 5 }),
    ];
    const flat = splitRuns(gapped).flatMap((run) => run.points);
    // No interpolation to fill the two gaps, no forward-fill, no re-sort.
    expect(flat.map((p) => p.date)).toEqual(gapped.map((p) => p.date));
    expect(flat.map((p) => p.value)).toEqual(gapped.map((p) => p.value));
  });

  it("does not treat a base point's null step_days as a gap", () => {
    // A base opens a run; it does not break one, and it must not produce a
    // dashed connector to a point that does not exist.
    expect(splitRuns(daily)[0].gapFrom).toBeNull();
  });

  it("handles an empty series without inventing a run", () => {
    expect(splitRuns([])).toEqual([]);
  });
});

// --- section 13.3: a flat chart stays flat ----------------------------------

describe("indexDomain refuses to amplify a flat index", () => {
  it("spans at least +/-1 % around the base level", () => {
    const domain = indexDomain(
      series({
        points: [
          point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
          point({ date: "2026-09-07", value: "1000.1065" }),
        ],
      }),
    );
    expect(domain).not.toBeNull();
    const [lo, hi] = domain!;
    expect(lo).toBeLessThanOrEqual(990);
    expect(hi).toBeGreaterThanOrEqual(1010);
    // A fitted domain would be [1000.00, 1000.11] and would turn a +0.01 %
    // week into a mountain range. The whole move must occupy well under a
    // twentieth of the axis.
    expect((1000.1065 - 1000) / (hi - lo)).toBeLessThan(0.05);
  });

  it("widens for real data outside that band rather than clipping it", () => {
    const domain = indexDomain(
      series({
        points: [
          point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
          point({ date: "2026-09-04", value: "1400.0000" }),
          point({ date: "2026-09-05", value: "700.0000" }),
        ],
      }),
    );
    const [lo, hi] = domain!;
    expect(lo).toBeLessThanOrEqual(700);
    expect(hi).toBeGreaterThanOrEqual(1400);
  });

  it("anchors on starting_value when the window excludes the base point", () => {
    const domain = indexDomain(
      series({
        starting_value: "1200.0000",
        points: [point({ date: "2026-09-07", value: "1200.0500" })],
      }),
    );
    const [lo, hi] = domain!;
    expect(lo).toBeLessThanOrEqual(1188);
    expect(hi).toBeGreaterThanOrEqual(1212);
  });

  it("has no domain for an empty series", () => {
    expect(indexDomain(series({ points: [] }))).toBeNull();
  });
});

// --- the change is rendered, not converted ----------------------------------

describe("change formatting keeps the server's units", () => {
  const change = {
    absolute: "0.1065",
    pct: "0.010650",
    from_date: "2026-09-03",
    to_date: "2026-09-07",
    spans_break: false,
  };

  it("reads pct as percent, not as a fraction", () => {
    // "0.010650" beside "0.1065" on a 1000 base is 0.01 %. A client
    // multiplying by 100 would print "+1.07%".
    expect(formatPctChange(change)).toBe("+0.01%");
  });

  it("signs a fall without borrowing the admin surface's red", () => {
    expect(formatPctChange({ ...change, pct: "-0.850000" })).toBe("−0.85%");
    expect(formatAbsoluteChange({ ...change, absolute: "-8.5000" })).toBe("−8.50");
  });

  it("marks a genuine zero as neither a rise nor a fall", () => {
    expect(formatPctChange({ ...change, pct: "0" })).toBe("0.00%");
    expect(formatAbsoluteChange({ ...change, absolute: "0" })).toBe("0.00");
  });
});
