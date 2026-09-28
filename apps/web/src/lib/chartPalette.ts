/** Existing public history-chart palette, shared by print and release charts.
 * CSS tokens inherit the public theme; colours identify series, not direction. */
export const PUBLIC_CHART_PALETTE = {
  gold: "var(--accent-gold)",
  teal: "var(--accent-teal)",
  parchment: "var(--parchment)",
  blue: "var(--signal-blue)",
  purple: "var(--signal-purple)",
  coral: "var(--accent-coral)",
  muted: "var(--text-muted)",
} as const;
