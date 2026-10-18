/** The canonical Atlas compass (header, error page). Decorative: callers
 * supply the accessible name. Size it with CSS on the svg. */
export function CompassMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 36 36" fill="none" focusable="false" aria-hidden="true" className={className}>
      <circle cx="18" cy="18" r="16" stroke="#33565b" />
      <circle cx="18" cy="18" r="12.5" stroke="#6fb5b0" />
      <path d="M18 5 20.5 15.5 31 18 20.5 20.5 18 31 15.5 20.5 5 18 15.5 15.5Z" stroke="#6fb5b0" fill="#12262a" />
      <path d="M18 5 20.5 15.5 18 18 15.5 15.5Z" fill="#d6a84f" />
      <circle cx="18" cy="18" r="1.5" fill="#eef2f2" />
    </svg>
  );
}
