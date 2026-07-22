import { Badge } from "./Badge";

export type ConfidenceLevel = "exact" | "high" | "medium" | "low" | "very_low" | "unknown";

const CONFIDENCE_LABELS: Record<ConfidenceLevel, string> = {
  exact: "Exact",
  high: "High",
  medium: "Medium",
  low: "Low",
  very_low: "Very low",
  unknown: "Unknown",
};

const CONFIDENCE_CLASS: Record<ConfidenceLevel, string> = {
  exact: "confidence-exact",
  high: "confidence-high",
  medium: "confidence-medium",
  low: "confidence-low",
  very_low: "confidence-very-low",
  unknown: "confidence-unknown",
};

export function ConfidenceBadge({ level }: { level: ConfidenceLevel | string }) {
  const normalized: ConfidenceLevel =
    level in CONFIDENCE_LABELS ? (level as ConfidenceLevel) : "unknown";
  return (
    <Badge label={CONFIDENCE_LABELS[normalized]} className={CONFIDENCE_CLASS[normalized]} />
  );
}
