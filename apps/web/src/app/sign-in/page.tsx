import type { Session } from "next-auth";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/AppHeader";
import { AccountHero, accountSurfaceStyles as styles } from "@/components/ui/AccountSurface";
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
  let session: Session | null = null;
  try {
    session = await auth();
  } catch {
    // An unreadable session is treated as signed out; the invite is the same.
  }
  // Already a collector: nothing to invite to, go where they were heading.
  if (session?.sessionKind === "collector") redirect(callbackUrl);
  // Only a live admin session is worth a word. An expired one grants nothing
  // and Google sign-in simply replaces it, exactly as for a signed-out visitor.
  const adminSignedIn = session?.sessionKind === "admin" && session.adminSessionExpired !== true;

  return (
    <div className={styles.root}>
      <AppHeader />
      <main className={styles.main}>
        <AccountHero
          aside={
            <ol className={styles.route} aria-label="What an account does">
              {ACCOUNT_USES.map((use, index) => (
                <li key={use}>
                  <span className={styles.stop} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  <span>{use}</span>
                </li>
              ))}
            </ol>
          }
        >
          <p className={styles.kicker}>Collector account</p>
          <h1 className={styles.title}>Track what your cards are worth</h1>
          <p className={styles.supporting}>
            Sign in with Google to start a collection. Card prices and the market stay open to everyone, with or
            without an account.
          </p>
          <section aria-labelledby="sign-in-heading" className={styles.actions}>
            <h2 id="sign-in-heading" className="sr-only">Sign in</h2>
            {adminSignedIn && (
              <p className={styles.notice} data-admin-note>
                You are signed in as the site admin. Collection pages need a collector account, which uses Google
                sign-in. Signing in with Google ends the admin session.
              </p>
            )}
            {googleConfigured ? (
              <>
                <GoogleSignInButton callbackUrl={callbackUrl} />
                <p className={styles.note} data-invite-only>
                  Sign-in is invite-only while accounts are being tested. If your Google account has not been
                  invited yet, Google will not let it sign in.
                </p>
              </>
            ) : (
              <p className={styles.notice} data-sign-in-closed>
                Collector sign-in is not open yet. You can still look up any card and follow the market without
                an account.
              </p>
            )}
          </section>
          <p className={styles.privacy}>
            We keep your Google name and email and the cards you add, nothing else from Google.{" "}
            <Link href="/privacy">Privacy (draft)</Link>
          </p>
          <nav aria-label="Keep browsing" className={styles.links}>
            <Link href="/cards">Look up card prices</Link>
            <Link href="/analytics">Follow the market</Link>
            <Link href="/">Home</Link>
          </nav>
        </AccountHero>
      </main>
    </div>
  );
}
