// Imported by next.config.ts, so no "@/" imports here (see cspImageOrigin.ts).

/** The `connect-src` origin the browser SDK posts to, or null when unset.
 * An invalid DSN throws, failing the build rather than shipping a CSP that
 * silently blocks error reports (same call as R2_PUBLIC_BASE_URL). */
export function sentryIngestOrigin(dsn: string | undefined): string | null {
  const value = dsn?.trim();
  if (!value) return null;
  const url = new URL(value);
  if (url.protocol !== "https:") throw new Error("NEXT_PUBLIC_SENTRY_DSN must be an https URL");
  return url.origin;
}
