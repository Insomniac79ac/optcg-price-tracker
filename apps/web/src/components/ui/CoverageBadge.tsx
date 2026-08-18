import { Badge } from "./Badge";
import type { MarketIndex } from "@/lib/api";

type CoverageStatus = MarketIndex["coverage_status"];

const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  full: "2 sources",
  limited: "limited coverage",
  none: "no sources",
};

/** Collector palette, not the operational one.
 *
 * This badge only ever renders on collector-facing surfaces (its sole
 * consumer is MarketIndexValue, and the /cards and /prints tiles both pass
 * showCoverage={false} and state coverage by listing the real per-source
 * prices instead) - so Discover, Market Index and the card detail page were
 * the only places these chips appeared, all of them in the emerald/amber
 * signal vocabulary docs/interface_design_system.md reserves for the admin
 * surface. Teal is "trusted info", gold is the meaningful-highlight accent,
 * and a missing index stays fully muted. Coverage is a statement about
 * evidence, never a good/bad price signal, so nothing here is green or red. */
const COVERAGE_TONE: Record<CoverageStatus, string> = {
  full: "bg-accent-teal/15 text-accent-teal-hover ring-1 ring-inset ring-accent-teal/30",
  limited: "bg-accent-gold/12 text-accent-gold ring-1 ring-inset ring-accent-gold/30",
  none: "bg-bg-card text-text-muted ring-1 ring-inset ring-border-default",
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
