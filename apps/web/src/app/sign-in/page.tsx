import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { PageHeader } from "@/components/ui/PageHeader";
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

/** The neutral "you need an account for this" landing page that proxy.ts
 * sends signed-out visitors to for collector-only routes (never
 * /market/movers - see proxy.ts). Deliberately contains no admin-login
 * functionality - that's a separate, not-yet-built flow (see
 * collector-blueprint.pdf Phase 10). */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const callbackUrl = sanitizeCallbackUrl(params.callbackUrl);
  const googleConfigured = isGoogleOAuthConfigured();

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-lg px-4 py-10">
        <PageHeader
          title="Account required"
          description="Collection, wishlist and grading features are tied to your own collector account. Browsing the card catalogue and Market Index does not require one."
        />

        <div className="panel space-y-4 p-6 text-sm text-text-secondary">
          {googleConfigured ? (
            <>
              <p>Sign in with Google to continue to the page you requested.</p>
              <GoogleSignInButton callbackUrl={callbackUrl} />
            </>
          ) : (
            <p>
              Collector accounts are not enabled in this staging build yet - Google sign-in
              has not been configured here. Check back once it has been set up.
            </p>
          )}

          <div className="flex gap-4 border-t border-border-muted pt-4 text-xs">
            <Link href="/" className="text-sky-400 hover:underline">
              ← Back to Discover
            </Link>
            <Link href="/search" className="text-sky-400 hover:underline">
              Browse Cards
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
