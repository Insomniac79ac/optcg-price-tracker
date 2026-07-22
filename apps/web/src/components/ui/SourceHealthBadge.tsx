import { Badge } from "./Badge";

export type SourceHealth = "healthy" | "degraded" | "stale" | "blocked" | "error" | "unknown";

const HEALTH_LABELS: Record<SourceHealth, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  stale: "Stale",
  blocked: "Blocked",
  error: "Error",
  unknown: "Unknown",
};

// Reuses the same risk-level scale (healthy=low ... error=critical) so the
// two badges read consistently side by side, without a second color system.
const HEALTH_CLASS: Record<SourceHealth, string> = {
  healthy: "risk-low",
  degraded: "risk-medium",
  stale: "risk-high",
  blocked: "risk-critical",
  error: "risk-critical",
  unknown: "confidence-unknown",
};

export function SourceHealthBadge({ health }: { health: SourceHealth | string }) {
  const normalized: SourceHealth = health in HEALTH_LABELS ? (health as SourceHealth) : "unknown";
  return <Badge label={HEALTH_LABELS[normalized]} className={HEALTH_CLASS[normalized]} />;
}
