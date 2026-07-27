import { Badge } from "./Badge";
import type { MarketIndex } from "@/lib/api";

const COVERAGE_LABEL: Record<MarketIndex["coverage_status"], string> = {
  full: "2 sources",
  limited: "limited coverage",
  none: "no sources",
};

const COVERAGE_TONE: Record<MarketIndex["coverage_status"], string> = {
  full: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  limited: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  none: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
};

/** Names how many/which sources back a Market Index value (design brief
 * "never imply a one-source index is a multi-source consensus") - "full"
 * gets a quiet source-count chip, "limited" is explicitly labelled so it's
 * never mistaken for the same thing, "none" only ever appears alongside
 * MarketIndexValue's "Index unavailable" text, never a price. */
export function CoverageBadge({
  coverageStatus,
  sourceCount,
}: {
  coverageStatus: MarketIndex["coverage_status"];
  sourceCount: number;
}) {
  const label =
    coverageStatus === "full" ? `${sourceCount} sources` : COVERAGE_LABEL[coverageStatus];
  return <Badge label={label} className={COVERAGE_TONE[coverageStatus]} />;
}
