import { Badge } from "./Badge";
import type { MarketIndex } from "@/lib/api";

type CoverageStatus = MarketIndex["coverage_status"];

const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  full: "2 sources",
  limited: "limited coverage",
  none: "no sources",
};

const COVERAGE_TONE: Record<CoverageStatus, string> = {
  full: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  limited: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  none: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
};

/** Names how many/which sources back a Market Index value (design brief
 * "never imply a one-source index is a multi-source consensus") - "full"
 * gets a quiet source-count chip, "limited" is explicitly labelled so it's
 * never mistaken for the same thing, "none" only ever appears alongside
 * MarketIndexValue's "Index unavailable" text, never a price.
 *
 * `sourceNames` (the display names of the sources that actually contributed
 * a value) lets a limited-coverage chip say which source that was - "Yuyu-Tei
 * only" is more use to a collector than "limited coverage", and is the same
 * honesty rule applied one level finer. Omitted, it falls back to the generic
 * wording, so existing callers are unchanged. */
export function CoverageBadge({
  coverageStatus,
  sourceCount,
  sourceNames,
}: {
  coverageStatus: CoverageStatus;
  sourceCount: number;
  sourceNames?: string[];
}) {
  let label: string;
  if (coverageStatus === "full") {
    label = `${sourceCount} sources`;
  } else if (coverageStatus === "limited" && sourceNames?.length === 1) {
    label = `${sourceNames[0]} only`;
  } else {
    label = COVERAGE_LABEL[coverageStatus];
  }
  return <Badge label={label} className={COVERAGE_TONE[coverageStatus]} />;
}
