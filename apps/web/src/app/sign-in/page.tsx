import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/AppHeader";
import { AtlasMapSurface, AtlasVisualSystem } from "@/components/ui/AtlasPrimitives";
import { auth } from "@/lib/auth";
import { sanitizeCallbackUrl } from "@/lib/callbackUrl";

import { GoogleSignInButton } from "./GoogleSignInButton";

const GOOGLE_PLACEHOLDER = "change-me";

/** True only when real Google OAuth credentials are configured - not merely
 * when the provider is registered (next-auth/src/lib/auth.ts always
 * registers GoogleProvider, so its presence in /api/auth/providers doesn't
 * mean sign-in would actually work). Reads process.env directly - this file
 * has no "use client" directive, so this runs server-side only and the
 * values themselves are never sent to the browser, only the derived
 * boolean below. */
function isGoogleOAuthConfigured(): boolean {
  const id = process.env.AUTH_GOOGLE_ID;
  const secret = process.env.AUTH_GOOGLE_SECRET;
  return Boolean(id && secret && id !== GOOGLE_PLACEHOLDER && secret !== GOOGLE_PLACEHOLDER);
}

const ACCOUNT_USES = [
  "Keep the exact versions you own, from any card page.",
  "See what your collection is worth, using the same Market Value as every card page.",
  "Follow how it moves over 7 days, 30 days and since you started.",
] as const;

/** The sign-in invite every collector route sends a visitor to who is not
 * signed in as a collector (src/proxy.ts): signed-out visitors, and admin
 * sessions, which have no collector account behind them (PLAN §D1, §D5).
 * It always offers a next step: the Google button when sign-in is open,
 * and the public pages either way. No admin login here - that is
 * /admin/login. */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const callbackUrl = sanitizeCallbackUrl(params.callbackUrl);
  const googleConfigured = isGoogleOAuthConfigured();
  let sessionKind: string | undefined;
  try {
    sessionKind = (await auth())?.sessionKind;
  } catch {
    // An unreadable session is treated as signed out; the invite is the same.
  }
  // Already a collector: nothing to invite to, go where they were heading.
  if (sessionKind === "collector") redirect(callbackUrl);
  const adminSignedIn = sessionKind === "admin";

  return (
    <div className="min-h-screen">
      <AppHeader />
      <AtlasVisualSystem>
        <main className="mx-auto max-w-2xl px-4 pb-12 pt-6 sm:pt-12">
          <AtlasMapSurface>
            <header className="px-5 py-7 sm:px-8 sm:py-9">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent-gold">Collector account</p>
              <h1 className="mt-2 font-display text-[30px] font-semibold leading-[1.1] tracking-tight text-text-primary sm:text-[38px]">
                Track what your cards are worth
              </h1>
              <p className="mt-3 max-w-[34rem] text-[15px] leading-7 text-text-secondary">
                Sign in with Google to start a collection. Card prices and the market stay open to everyone,
                with or without an account.
              </p>
            </header>
          </AtlasMapSurface>

          <section aria-labelledby="sign-in-heading" className="panel mt-6 px-5 py-6 sm:px-8">
            <h2 id="sign-in-heading" className="sr-only">Sign in</h2>
            {adminSignedIn && (
              <p className="mb-4 rounded-control border border-border-muted px-3 py-2 text-sm leading-6 text-text-secondary" data-admin-note>
                You are signed in as the site admin. Collection pages need a collector account, which uses Google
                sign-in. Signing in with Google ends the admin session.
              </p>
            )}
            {googleConfigured ? (
              <div className="space-y-3">
                <GoogleSignInButton callbackUrl={callbackUrl} />
                <p className="text-sm leading-6 text-text-muted" data-invite-only>
                  Sign-in is invite-only while accounts are being tested. If your Google account has not been
                  invited yet, Google will not let it sign in.
                </p>
              </div>
            ) : (
              <p className="text-sm leading-6 text-text-secondary" data-sign-in-closed>
                Collector sign-in is not open yet. You can still look up any card and follow the market without
                an account.
              </p>
            )}

            <ul className="mt-6 space-y-3 border-t border-border-muted pt-5">
              {ACCOUNT_USES.map((use, index) => (
                <li key={use} className="flex gap-3 text-sm leading-6 text-text-secondary">
                  <span className="mt-0.5 font-mono text-[12px] text-accent-gold" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span>{use}</span>
                </li>
              ))}
            </ul>
            <p className="mt-5 text-xs leading-5 text-text-muted">
              We keep your Google name and email and the cards you add, nothing else from Google.{" "}
              <Link href="/privacy" className="text-accent-teal hover:text-accent-teal-hover">
                Privacy (draft)
              </Link>
            </p>
          </section>

          <nav aria-label="Keep browsing" className="mt-6 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <Link href="/cards" className="inline-flex min-h-11 items-center font-medium text-accent-teal hover:text-accent-teal-hover md:min-h-0">
              Look up card prices
            </Link>
            <Link href="/analytics" className="inline-flex min-h-11 items-center font-medium text-accent-teal hover:text-accent-teal-hover md:min-h-0">
              Follow the market
            </Link>
            <Link href="/" className="inline-flex min-h-11 items-center font-medium text-accent-teal hover:text-accent-teal-hover md:min-h-0">
              Home
            </Link>
          </nav>
        </main>
      </AtlasVisualSystem>
    </div>
  );
}
