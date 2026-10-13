"use client";

import { Analytics } from "@vercel/analytics/next";

import { analyticsEnabled, scrubAnalyticsEvent } from "@/lib/analytics";

/** Vercel Web Analytics page views (cookieless). Renders nothing until
 * NEXT_PUBLIC_VERCEL_WEB_ANALYTICS=1 - see src/lib/analytics.ts. */
export function SiteAnalytics() {
  if (!analyticsEnabled()) return null;
  return <Analytics beforeSend={scrubAnalyticsEvent} />;
}
