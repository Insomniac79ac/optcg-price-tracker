import type { Instrumentation } from "next";

import { sentryDsn, sentryOptions } from "@/lib/sentry";

// Server and edge error tracking (src/lib/sentry.ts). Without
// NEXT_PUBLIC_SENTRY_DSN neither hook loads the SDK or does anything.

export async function register() {
  const dsn = sentryDsn();
  if (!dsn) return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.init({
    ...sentryOptions(dsn),
    // Errors only: no release-health session per incoming request.
    integrations: (defaults) => [
      ...defaults.filter((integration) => integration.name !== "Http"),
      Sentry.httpIntegration({ trackIncomingRequestsAsSessions: false }),
    ],
  });
}

export const onRequestError: Instrumentation.onRequestError = async (...args) => {
  if (!sentryDsn()) return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.captureRequestError(...args);
};
