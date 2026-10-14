import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { AtlasMapSurface, AtlasSectionIntro, AtlasVisualSystem } from "@/components/ui/AtlasPrimitives";
import { loadAccountOverview, type AccountOverview } from "@/lib/accountServer";
import { auth } from "@/lib/auth";
import { collectorIdentity, type CollectorIdentity } from "@/lib/collectorApi";
import { formatDate } from "@/lib/format";

import { DeleteAccount, SignOutButton } from "./AccountActions";

export const dynamic = "force-dynamic";

const OTHER_CURRENCIES = ["USD", "EUR", "GBP"] as const;

const LINK = "inline-flex min-h-11 items-center rounded-control border border-border-default px-4 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 md:min-h-9";

/** The signed-in collector's account (PLAN §D4): profile, preferences,
 * export, delete, sign out. src/proxy.ts already sends anyone who is not a
 * collector to /sign-in; this page checks the session again on the server
 * and never trusts the proxy alone. All API calls happen server-side or
 * through /api/me; the page holds no token. */
export default async function AccountPage() {
  const identity = collectorIdentity(await auth());
  if (!identity) return <NotSignedIn />;
  const overview = await loadAccountOverview(identity);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <AtlasVisualSystem>
        <main className="mx-auto max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
          <AtlasMapSurface>
            <header className="flex items-center gap-4 px-5 py-7 sm:gap-5 sm:px-8 sm:py-9">
              <Monogram identity={identity} />
              <div className="min-w-0">
                <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent-gold">Your account</p>
                <h1 className="mt-1 truncate font-display text-[28px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[34px]">
                  {identity.name ?? identity.email}
                </h1>
                <p className="mt-1 truncate text-sm text-text-muted">{identity.email}</p>
              </div>
            </header>
          </AtlasMapSurface>

          {overview.state === "ok" ? <AccountSections identity={identity} overview={overview} /> : <Unavailable state={overview.state} />}
        </main>
      </AtlasVisualSystem>
    </div>
  );
}

function Monogram({ identity }: { identity: CollectorIdentity }) {
  const initial = (identity.name ?? identity.email).trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden="true"
      className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-accent-gold/60 font-display text-2xl font-semibold text-accent-gold sm:h-16 sm:w-16"
    >
      {initial}
    </span>
  );
}

function AccountSections({ identity, overview }: { identity: CollectorIdentity; overview: Extract<AccountOverview, { state: "ok" }> }) {
  const { profile, preferences } = overview;
  return (
    <div className="mt-8 space-y-10">
      <section aria-labelledby="profile">
        <AtlasSectionIntro id="profile" number="01" title="Profile" description="Managed by Google. Change your name or email in your Google account." />
        <dl className="panel mt-4 grid gap-x-6 gap-y-3 px-5 py-4 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-text-muted">Name</dt>
          <dd className="min-w-0 break-words text-text-primary">{profile.name ?? identity.name ?? "—"}</dd>
          <dt className="text-text-muted">Email</dt>
          <dd className="min-w-0 break-words text-text-primary">{profile.email}</dd>
          <dt className="text-text-muted">Member since</dt>
          <dd className="text-text-primary">{formatDate(profile.member_since)}</dd>
        </dl>
      </section>

      <section aria-labelledby="preferences">
        <AtlasSectionIntro id="preferences" number="02" title="Preferences" description="Your collection is private. Only you can see it." />
        <div className="panel mt-4 px-5 py-4">
          <label htmlFor="currency" className="block text-sm text-text-muted">Currency</label>
          <select
            id="currency"
            name="currency"
            defaultValue={preferences.currency}
            className="mt-2 min-h-11 w-full max-w-xs rounded-control border border-border-default bg-bg-surface px-3 text-sm text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 md:min-h-9"
          >
            <option value="JPY">JPY (¥)</option>
            {OTHER_CURRENCIES.map((code) => (
              <option key={code} value={code} disabled>
                {code} (more currencies later)
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs leading-5 text-text-muted">Prices are recorded in yen. Other currencies are coming later.</p>
        </div>
      </section>

      <section aria-labelledby="export">
        <AtlasSectionIntro id="export" number="03" title="Export my data" description="Everything we store about you, made when you ask. Nothing is kept on our side." />
        <div className="mt-4 flex flex-wrap gap-3">
          <a href="/api/me/export" download className={LINK}>All data (JSON)</a>
          <a href="/api/me/export/collection.csv" download className={LINK}>Collection (CSV)</a>
          <a href="/api/me/export/watchlist.csv" download className={LINK}>Watchlist (CSV)</a>
        </div>
      </section>

      <section aria-labelledby="delete">
        <AtlasSectionIntro
          id="delete"
          number="04"
          title="Delete my account"
          description="Removes your account, collection, watchlist, preferences and value history for good. This cannot be undone. Your Google account is not affected."
        />
        <div className="panel mt-4 px-5 py-4">
          <DeleteAccount />
        </div>
      </section>

      <section aria-labelledby="sign-out" className="border-t border-border-muted pt-6">
        <h2 id="sign-out" className="sr-only">Sign out</h2>
        <SignOutButton />
      </section>
    </div>
  );
}

function Unavailable({ state }: { state: "disabled" | "error" }) {
  return (
    <div className="panel mt-8 space-y-4 px-5 py-5 text-sm leading-6 text-text-secondary">
      {state === "disabled" ? (
        <p data-accounts-disabled>Collector accounts are not switched on yet, so there is nothing stored for you.</p>
      ) : (
        <p role="alert">Your account details could not be loaded just now. Please try again in a moment.</p>
      )}
      <SignOutButton />
    </div>
  );
}

function NotSignedIn() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-2xl px-4 py-12 text-sm text-text-secondary">
        <p>
          Your account page needs a collector sign-in.{" "}
          <Link href="/sign-in?callbackUrl=%2Faccount" className="font-medium text-accent-teal hover:text-accent-teal-hover">
            Sign in
          </Link>
        </p>
      </main>
    </div>
  );
}
