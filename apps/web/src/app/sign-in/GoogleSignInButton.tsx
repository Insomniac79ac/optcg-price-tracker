"use client";

import { signIn } from "next-auth/react";

import { trackEvent } from "@/lib/analytics";

/** Client boundary for the one bit of this page that needs next-auth/react
 * - the parent page is a Server Component so it can read process.env
 * (whether Google OAuth is actually configured) without ever shipping the
 * values themselves to the browser. `callbackUrl` has already been
 * validated by the parent (see src/lib/callbackUrl.ts) before it reaches
 * here. Styled like the homepage's gold "Sign in" pill: the one primary
 * action on the page. */
export function GoogleSignInButton({ callbackUrl }: { callbackUrl: string }) {
  return (
    <button
      type="button"
      className="inline-flex min-h-12 w-full items-center justify-center gap-2.5 rounded-control bg-accent-gold px-5 text-sm font-semibold text-black/85 transition-colors hover:bg-accent-gold-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-gold/60 sm:w-auto sm:justify-self-start"
      onClick={() => {
        trackEvent("sign_in_started", { page_type: "sign_in" });
        void signIn("google", { callbackUrl });
      }}
    >
      <GoogleMark />
      Sign in with Google
    </button>
  );
}

/** Google's "G", monochrome so it sits on the gold without a white tile. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M21.35 11.1H12v2.98h5.35c-.23 1.4-1.66 4.1-5.35 4.1-3.22 0-5.85-2.67-5.85-5.95S8.78 6.28 12 6.28c1.83 0 3.06.78 3.76 1.45l2.56-2.47C16.68 3.73 14.55 2.8 12 2.8 6.92 2.8 2.8 6.92 2.8 12s4.12 9.2 9.2 9.2c5.31 0 8.83-3.73 8.83-8.98 0-.6-.07-1.06-.15-1.52Z"
      />
    </svg>
  );
}
