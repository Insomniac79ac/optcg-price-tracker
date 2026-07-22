import { Badge } from "./Badge";

export type RiskLevel = "low" | "medium" | "high" | "critical";

const RISK_LABELS: Record<RiskLevel, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

/** Aliases other pages' local risk vocabularies onto the canonical
 * low/medium/high/critical scale, so they can share this one badge instead
 * of each re-declaring their own color map. Extend as new vocabularies show
 * up rather than adding a second badge component. */
const RISK_ALIASES: Record<string, RiskLevel> = {
  ok: "low",
  review: "medium",
  warning: "high",
  critical: "critical",
  low: "low",
  medium: "medium",
  high: "high",
};

export function normalizeRiskLevel(value: string): RiskLevel {
  return RISK_ALIASES[value] ?? "medium";
}

export function RiskBadge({ level }: { level: RiskLevel | string }) {
  const normalized: RiskLevel = (["low", "medium", "high", "critical"] as const).includes(
    level as RiskLevel,
  )
    ? (level as RiskLevel)
    : normalizeRiskLevel(level);
  return <Badge label={RISK_LABELS[normalized]} className={`risk-${normalized}`} />;
}
