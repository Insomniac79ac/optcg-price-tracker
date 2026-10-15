import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { AccountChapter, AccountHero, accountSurfaceStyles as styles } from "@/components/ui/AccountSurface";
import { loadAccountOverview, type AccountOverview } from "@/lib/accountServer";
import { auth } from "@/lib/auth";
import { collectorIdentity, type CollectorIdentity } from "@/lib/collectorApi";
import { formatDate } from "@/lib/format";

import { DeleteAccount, SignOutButton } from "./AccountActions";

export const dynamic = "force-dynamic";

const OTHER_CURRENCIES = ["USD", "EUR", "GBP"] as const;

const LINK = "inline-flex min-h-11 items-center rounded-control border border-[#3e696a] px-4 text-sm font-medium text-[#8dc9c4] transition-colors hover:border-accent-teal hover:text-text-primary md:min-h-10";

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
    <div className={styles.root}>
      <AppHeader />
      <main className={styles.main}>
        <AccountHero>
          <p className={styles.kicker}>Your account</p>
          <div className={`${styles.identity} mt-3`}>
            <Monogram identity={identity} />
            <div className="min-w-0">
              <h1 className={`${styles.title} !mt-0`}>{identity.name ?? identity.email}</h1>
              <p className={styles.email}>{identity.email}</p>
            </div>
          </div>
        </AccountHero>

        {overview.state === "ok" ? <AccountSections identity={identity} overview={overview} /> : <Unavailable state={overview.state} />}
      </main>
    </div>
  );
}

function Monogram({ identity }: { identity: CollectorIdentity }) {
  const initial = (identity.name ?? identity.email).trim().charAt(0).toUpperCase() || "?";
  return (
    <span aria-hidden="true" className={styles.monogram}>
      {initial}
    </span>
  );
}

function AccountSections({ identity, overview }: { identity: CollectorIdentity; overview: Extract<AccountOverview, { state: "ok" }> }) {
  const { profile, preferences } = overview;
  return (
    <div className={styles.sections}>
      <section aria-labelledby="profile">
        <AccountChapter id="profile" number="01" title="Profile">Managed by Google. Change your name or email in your Google account.</AccountChapter>
        <dl className={`${styles.panel} ${styles.facts}`}>
          <dt>Name</dt>
          <dd>{profile.name ?? identity.name ?? "—"}</dd>
          <dt>Email</dt>
          <dd>{profile.email}</dd>
          <dt>Member since</dt>
          <dd>{formatDate(profile.member_since)}</dd>
        </dl>
      </section>

      <section aria-labelledby="preferences">
        <AccountChapter id="preferences" number="02" title="Preferences">Your collection is private. Only you can see it.</AccountChapter>
        <div className={styles.panel}>
          <label htmlFor="currency" className="block text-sm text-[#a0b2b6]">Currency</label>
          <select
            id="currency"
            name="currency"
            defaultValue={preferences.currency}
            className="mt-2 min-h-11 w-full max-w-xs rounded-control border border-[#32464d] bg-[#0c1115] px-3 text-sm text-text-primary focus:outline-none md:min-h-10"
          >
            <option value="JPY">JPY (¥)</option>
            {OTHER_CURRENCIES.map((code) => (
              <option key={code} value={code} disabled>
                {code} (more currencies later)
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs leading-5 text-[#a0b2b6]">Prices are recorded in yen. Other currencies are coming later.</p>
        </div>
      </section>

      <section aria-labelledby="export">
        <AccountChapter id="export" number="03" title="Export my data">Everything we store about you, made when you ask. Nothing is kept on our side.</AccountChapter>
        <div className="flex flex-wrap gap-3">
          <a href="/api/me/export" download className={LINK}>All data (JSON)</a>
          <a href="/api/me/export/collection.csv" download className={LINK}>Collection (CSV)</a>
          <a href="/api/me/export/watchlist.csv" download className={LINK}>Watchlist (CSV)</a>
        </div>
      </section>

      <section aria-labelledby="delete">
        <AccountChapter id="delete" number="04" title="Delete my account">
          Removes your account, collection, watchlist, preferences and value history for good. This cannot be undone.
          Your Google account is not affected.
        </AccountChapter>
        <div className={`${styles.panel} ${styles.danger}`}>
          <DeleteAccount />
        </div>
      </section>

      <section aria-labelledby="sign-out" className={`${styles.wide} border-t border-[#2b3d43] pt-6`}>
        <h2 id="sign-out" className="sr-only">Sign out</h2>
        <SignOutButton />
      </section>
    </div>
  );
}

function Unavailable({ state }: { state: "disabled" | "error" }) {
  return (
    <div className={`${styles.panel} mt-8 max-w-3xl space-y-4 text-sm leading-6 text-[#b5c6cd]`}>
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
    <div className={styles.root}>
      <AppHeader />
      <main className={`${styles.main} pt-12 text-sm text-[#b5c6cd]`}>
        <p>
          Your account page needs a collector sign-in.{" "}
          <Link href="/sign-in?callbackUrl=%2Faccount" className="font-medium text-[#8dc9c4] hover:text-text-primary">
            Sign in
          </Link>
        </p>
      </main>
    </div>
  );
}
