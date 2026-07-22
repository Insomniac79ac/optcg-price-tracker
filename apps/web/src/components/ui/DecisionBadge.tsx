import { Badge } from "./Badge";

export type DecisionAction =
  | "review_buy"
  | "review_sell"
  | "wait"
  | "hold"
  | "monitor"
  | "grade_first"
  | "missing_data"
  | "skip";

const DECISION_LABELS: Record<DecisionAction, string> = {
  review_buy: "Review buy",
  review_sell: "Review sell",
  wait: "Wait",
  hold: "Hold",
  monitor: "Monitor",
  grade_first: "Grade first",
  missing_data: "Missing data",
  skip: "Skip",
};

// bg/text/ring pattern matches every other badge in the app (RarityBadge,
// SourceBadge, ...) - kept as Tailwind utilities rather than new CSS-layer
// classes since this vocabulary is specific to buy/sell decision support.
const DECISION_CLASS: Record<DecisionAction, string> = {
  review_buy: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  review_sell: "bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/30",
  wait: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  hold: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
  monitor: "bg-cyan-500/15 text-cyan-300 ring-1 ring-inset ring-cyan-500/30",
  grade_first: "bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/30",
  missing_data: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  skip: "bg-neutral-800/60 text-neutral-500 ring-1 ring-inset ring-neutral-700/40",
};

export function DecisionBadge({ action }: { action: DecisionAction | string }) {
  const normalized: DecisionAction = action in DECISION_LABELS ? (action as DecisionAction) : "skip";
  return <Badge label={DECISION_LABELS[normalized]} className={DECISION_CLASS[normalized]} />;
}
