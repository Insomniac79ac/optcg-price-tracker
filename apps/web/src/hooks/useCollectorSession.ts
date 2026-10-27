"use client";

import { useSession, type SessionContextValue } from "next-auth/react";

const SIGNED_OUT: SessionContextValue = Object.freeze({
  data: null,
  status: "unauthenticated",
  update: async () => null,
});

/** The collector session, for every client component (lint forbids importing next-auth's
 * `useSession` anywhere else).
 *
 * Next.js does not guarantee the root layout around every render: for an unrecognised
 * URL-encoded server-action POST (scanner traffic, e.g. `POST /` with a `Next-Action` header)
 * it renders `not-found.tsx` on its own, without the root layout and therefore without
 * `<AuthSessionProvider>`. next-auth's `useSession()` then returns undefined in production
 * (and throws in development), and destructuring it crashed the 404 with a 500 (Sentry,
 * staging, 2026-10-27). With no provider there is no session, so the chrome renders as
 * signed out. */
export function useCollectorSession(): SessionContextValue {
  return useSession() ?? SIGNED_OUT;
}
