/** The retained CPI mover component is separate from monetary Market Value. */
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { IndexMoversPanel } from "@/components/ui/IndexMoversPanel";
import type { IndexMover, IndexMovers } from "@/lib/cardPirateIndex";
const BANDAI = "https://www.onepiece-cardgame.com/images/cardlist/card";

/** Staging's real 2026-09-07 movers, verbatim from
 * GET /analytics/index/movers?date=2026-09-07. */
const LAW: IndexMover = {
  card_print_id: 5686,
  card_code: "OP01-047",
  name: "Trafalgar Law",
  rarity: "SP CARD",
  display_image_url: `${BANDAI}/OP01-047_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 17000,
  current_value_jpy: 10000,
  direction: "down",
  raw_pct: -41.18,
  capped_log_return: "-0.223143551314209756",
  was_capped: true,
  contribution_log_return: "-0.000753863349034492",
  approx_index_points: "-0.7546",
  move_rank: 1,
  impact_rank: 1,
};

const ST_NAMI: IndexMover = {
  card_print_id: 6796,
  card_code: "ST01-007",
  name: "Nami",
  rarity: "C",
  display_image_url: `${BANDAI}/ST01-007_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 2000,
  current_value_jpy: 1500,
  direction: "down",
  raw_pct: -25.0,
  capped_log_return: "-0.223143551314209756",
  was_capped: true,
  contribution_log_return: "-0.000753863349034492",
  approx_index_points: "-0.7546",
  move_rank: 2,
  impact_rank: 2,
};

const OP_NAMI: IndexMover = {
  card_print_id: 6807,
  card_code: "OP01-016",
  name: "Nami",
  rarity: "R",
  display_image_url: `${BANDAI}/OP01-016_p1.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 3000,
  current_value_jpy: 3700,
  direction: "up",
  raw_pct: 23.33,
  capped_log_return: "0.209720530982069069",
  was_capped: false,
  contribution_log_return: "0.000708515307371855",
  approx_index_points: "0.7092",
  move_rank: 3,
  impact_rank: 3,
};

const HANCOCK: IndexMover = {
  card_print_id: 5687,
  card_code: "OP01-078",
  name: "Boa Hancock",
  rarity: "SP CARD",
  display_image_url: `${BANDAI}/OP01-078_p2.png?260821`,
  treatment: null,
  language: "jp",
  prior_value_jpy: 66000,
  current_value_jpy: 65000,
  direction: "down",
  raw_pct: -1.52,
  capped_log_return: "-0.015267472130788434",
  was_capped: false,
  contribution_log_return: "-0.000051579297739150",
  approx_index_points: "-0.0516",
  move_rank: 4,
  impact_rank: 4,
};

function movers(partial: Partial<IndexMovers> = {}): IndexMovers {
  return {
    as_of: "2026-09-07",
    prior_point_date: "2026-09-06",
    constituent_count: 296,
    movers_count: 4,
    unchanged_count: 292,
    chain_link_log_return: "-0.000850790688",
    movers: [LAW, ST_NAMI, OP_NAMI, HANCOCK],
    truncated: false,
    ...partial,
  };
}

/** Staging's real 2026-09-06: 296 constituents, none of which moved. */
function quietDay(): IndexMovers {
  return {
    as_of: "2026-09-06",
    prior_point_date: "2026-09-05",
    constituent_count: 296,
    movers_count: 0,
    unchanged_count: 296,
    chain_link_log_return: "0E-12",
    movers: [],
    truncated: false,
  };
}

/** Staging's real 2026-09-03 base point. */
function basePoint(): IndexMovers {
  return {
    as_of: "2026-09-03",
    prior_point_date: null,
    constituent_count: 0,
    movers_count: 0,
    unchanged_count: 0,
    chain_link_log_return: null,
    movers: [],
    truncated: false,
  };
}


it("retains exact-print destinations and CPI-specific impact", () => {
  render(<IndexMoversPanel movers={movers()} status="ready" />);
  expect(document.querySelector('a[href="/prints/5687"]')).toBeInTheDocument();
  expect(screen.getByTestId("index-movers")).toHaveTextContent("Index impact");
  expect(screen.getByTestId("movers-meta")).toHaveTextContent("4 of 296");
});
it("keeps a quiet CPI day distinct from the initial base point", () => {
  const view = render(<IndexMoversPanel movers={quietDay()} status="ready" />);
  expect(screen.getByTestId("index-movers")).toHaveTextContent("No cards moved on this published day.");
  view.rerender(<IndexMoversPanel movers={basePoint()} status="ready" />);
  expect(screen.getByTestId("index-movers")).toHaveTextContent(/prior/i);
});
it("shows a local failure without fabricated rows", () => {
  render(<IndexMoversPanel movers={null} status="error" />);
  expect(screen.getByTestId("index-movers")).toHaveTextContent("We can't show the cards behind this move right now.");
  expect(document.querySelector('a[href^="/prints/"]')).not.toBeInTheDocument();
});
