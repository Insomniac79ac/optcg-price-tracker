import { sentryDsn, sentryOptions } from "@/lib/sentry";

// Browser error tracking (src/lib/sentry.ts). NEXT_PUBLIC_SENTRY_DSN is
// inlined at build time: without it the SDK chunk is never requested.
const dsn = sentryDsn();
if (dsn) {
  void import("@sentry/nextjs").then((Sentry) => Sentry.init(sentryOptions(dsn)));
}
