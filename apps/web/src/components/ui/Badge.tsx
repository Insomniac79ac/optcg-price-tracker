/** Generic pill primitive - the same `bg-x/15 text-x-300 ring-x/30` shape
 * every existing badge (RarityBadge, SourceBadge, ...) already hand-rolls.
 * New shared badges (RiskBadge, ConfidenceBadge, ...) build on this rather
 * than each re-declaring the span/className boilerplate. */
export function Badge({
  label,
  className = "",
  title,
}: {
  label: string;
  className?: string;
  title?: string;
}) {
  return (
    <span className={`badge ${className}`} title={title}>
      {label}
    </span>
  );
}
