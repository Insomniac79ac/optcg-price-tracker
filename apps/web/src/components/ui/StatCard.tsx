import type { ReactNode } from "react";

export type StatTone = "neutral" | "good" | "bad" | "gold";

const TONE_CLASS: Record<StatTone, string> = {
  neutral: "text-text-primary",
  good: "price-positive",
  bad: "price-negative",
  gold: "text-accent-gold",
};

/** Dense stat tile - consolidates the stat-card component that was
 * copy-pasted (identically) in buy-decisions/sell-decisions/portfolio-risk/
 * digest, plus the dashboard's inline `Stat` helper. */
export function StatCard({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: StatTone;
  hint?: ReactNode;
}) {
  return (
    <div className="panel px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className={`mono tabular mt-0.5 text-base font-semibold ${TONE_CLASS[tone]}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div>}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">{children}</div>;
}
