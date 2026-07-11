import Link from "next/link";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-6 px-4">
        <Link
          href="/dashboard"
          className="text-sm font-semibold tracking-tight text-neutral-100"
        >
          OPTCG Price Tracker
        </Link>
        <nav className="flex items-center gap-4 text-sm text-neutral-400">
          <Link href="/dashboard" className="hover:text-neutral-100">
            Dashboard
          </Link>
          <Link href="/collection" className="hover:text-neutral-100">
            Collection
          </Link>
          <Link href="/market/signals" className="hover:text-neutral-100">
            Market signals
          </Link>
          <Link href="/market/signal-events" className="hover:text-neutral-100">
            Signal events
          </Link>
          <Link href="/market/opportunities" className="hover:text-neutral-100">
            Opportunities
          </Link>
          <Link
            href="/admin/refresh-runs"
            className="hover:text-neutral-100"
          >
            Refresh runs
          </Link>
          <Link
            href="/admin/snkrdunk-candidates"
            className="hover:text-neutral-100"
          >
            SNKRDUNK candidates
          </Link>
          <Link href="/admin/alerts" className="hover:text-neutral-100">
            Alerts
          </Link>
          <Link href="/admin/card-audit" className="hover:text-neutral-100">
            Card audit
          </Link>
        </nav>
      </div>
    </header>
  );
}
