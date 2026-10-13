import { buildCommit } from "@/generated/buildVersion";

/** Error tracking (Sentry Developer, free tier; Collector v1 plan §F2, owner Q3).
 *
 * Everything is off unless NEXT_PUBLIC_SENTRY_DSN is set on the Vercel
 * project: no SDK is loaded, nothing is sent, and CSP is unchanged. The DSN
 * is public by design (it only allows sending events), so one NEXT_PUBLIC_
 * variable serves browser and server. It is still kept out of the repo.
 *
 * Privacy contract: sendDefaultPii false, no tracing, no session replay, no
 * release-health sessions (they would ping Sentry on every page view), no
 * user, and `scrubSentryEvent` removes Authorization/cookie headers, cookies,
 * request bodies and every query string (URLs can carry OAuth codes and
 * callback targets) before an event leaves the process. */

export function sentryDsn(): string | undefined {
  return process.env.NEXT_PUBLIC_SENTRY_DSN?.trim() || undefined;
}

export function sentryEnvironment(): string {
  return process.env.NEXT_PUBLIC_APP_ENV?.trim() || "staging";
}

export function sentryRelease(): string | undefined {
  const commit: string = buildCommit; // a literal in the generated file
  return commit && commit !== "unknown" ? commit : undefined;
}

const SENSITIVE_HEADER = /^(authorization|proxy-authorization|cookie|set-cookie|x-admin-token|x-admin-actor-assertion|x-api-key)$/i;

type Breadcrumb = { data?: Record<string, unknown> | null; message?: string | null };
type ScrubbableEvent = {
  request?: {
    url?: string;
    query_string?: unknown;
    cookies?: unknown;
    headers?: Record<string, unknown>;
    data?: unknown;
  };
  user?: unknown;
  breadcrumbs?: Breadcrumb[];
};

function stripQuery(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const cut = value.search(/[?#]/);
  return cut === -1 ? value : value.slice(0, cut);
}

/** `beforeSend` for browser and server events. Mutates and returns the event. */
export function scrubSentryEvent<T extends ScrubbableEvent>(event: T): T {
  const request = event.request;
  if (request) {
    delete request.cookies;
    delete request.data;
    delete request.query_string;
    if (request.url) request.url = stripQuery(request.url) as string;
    if (request.headers) {
      for (const key of Object.keys(request.headers)) {
        if (SENSITIVE_HEADER.test(key)) delete request.headers[key];
      }
    }
  }
  delete event.user;
  for (const crumb of event.breadcrumbs ?? []) {
    if (!crumb.data) continue;
    for (const key of ["url", "from", "to"]) {
      if (key in crumb.data) crumb.data[key] = stripQuery(crumb.data[key]);
    }
  }
  return event;
}

type Integration = { name: string };

/** Errors only: drop the per-page-view session ping. */
export function withoutSessionTracking<T extends Integration>(defaults: T[]): T[] {
  return defaults.filter((integration) => integration.name !== "BrowserSession");
}

/** The options both runtimes pass to Sentry.init(). */
export function sentryOptions(dsn: string) {
  return {
    dsn,
    environment: sentryEnvironment(),
    release: sentryRelease(),
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeSend: scrubSentryEvent,
    integrations: withoutSessionTracking,
  };
}
