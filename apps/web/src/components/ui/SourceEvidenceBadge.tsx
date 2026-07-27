import type { MarketIndexSourceValue } from "@/lib/api";

/** Subtle "what kind of evidence is this value based on" marker (design
 * brief "no large warning on every tile - a subtle listing-based/fallback
 * indicator accessible through text or tooltip"). A `transaction` value
 * (SNKRDUNK's sold-price median) gets no badge at all - it's the strongest
 * evidence type and needs no caveat. A `listing` value gets a quiet dot
 * badge; when it's specifically a fallback (SNKRDUNK's floor standing in
 * for too few recent sales), the tooltip/sr-only text says so explicitly -
 * this is the one place that guards against ever reading a floor price as
 * a completed sale. */
export function SourceEvidenceBadge({ value }: { value: MarketIndexSourceValue }) {
  if (value.evidence_type === "transaction") return null;

  const title = value.fallback_used
    ? "Based on the latest listing, not a completed sale - too few recent sales to use a transaction median."
    : "Based on a current listing, not a completed sale.";

  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] font-medium text-text-faint"
      title={title}
    >
      <span aria-hidden="true" className="h-1 w-1 rounded-full bg-text-faint" />
      <span className="sr-only">{title}</span>
      <span aria-hidden="true">{value.fallback_used ? "listing · fallback" : "listing"}</span>
    </span>
  );
}
