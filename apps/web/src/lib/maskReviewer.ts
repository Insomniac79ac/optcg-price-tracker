/** Presentation only. Never return a malformed audit identifier verbatim. */
export function maskReviewer(value: string | null | undefined): string {
  if (!value) return "Not returned";
  const match = /^([^\s@]+)@([^\s@]+\.[^\s@]+)$/.exec(value.trim());
  if (!match) return "Reviewer recorded";
  return `${match[1][0]}***@${match[2]}`;
}
