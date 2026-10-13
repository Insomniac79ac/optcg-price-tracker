import { sentryDsn } from "@/lib/sentry";

/** Sends an error caught by a React error boundary to Sentry (those never
 * reach window.onerror). A no-op without NEXT_PUBLIC_SENTRY_DSN. */
export function reportError(error: unknown): void {
  if (!sentryDsn()) return;
  void import("@sentry/nextjs").then((Sentry) => Sentry.captureException(error));
}
