"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  type CacheClearResponse,
  type CacheStatus,
  clearCache,
  fetchCacheStatus,
  getAdminToken,
} from "@/lib/api";

const CONFIRM_PHRASE = "CLEAR";

const HELPFUL_PREFIXES = [
  "dashboard",
  "collection_valuation",
  "collection_history",
  "market_signals",
  "market_signal_events",
  "market_opportunities",
  "market_report",
  "wishlist",
  "grading",
  "analytics_digest",
  "collection_analytics",
  "wishlist_analytics",
  "buy_decisions",
  "sell_decisions",
  "grading_analytics",
  "portfolio_risk",
];

export default function CachePage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<CacheStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchCacheStatus()
      .then((data) => {
        setStatus(data);
        setError(null);
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) {
          setUnauthorized(true);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load cache status.");
        }
      });
  }

  useEffect(() => {
    setUnauthorized(!getAdminToken());
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Cache</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Short-lived cache for dashboard and market read endpoints.
        </p>

        {unauthorized && (
          <AdminAuthGate
            onTokenSaved={() => {
              setUnauthorized(false);
              load();
            }}
          />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            {error && (
              <div className="rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                {error}
              </div>
            )}

            <SummaryCards status={status} onRefresh={load} />
            <ClearCacheSection onCleared={load} />
            <HelpfulPrefixes />

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/performance"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Performance
              </Link>
              <Link
                href="/admin/job-locks"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Job locks
              </Link>
              <Link
                href="/admin/data-retention"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Data retention
              </Link>
              <Link
                href="/admin/file-jobs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                File jobs
              </Link>
              <Link
                href="/admin/actions"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Admin actions
              </Link>
              <Link
                href="/admin/logs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                App logs
              </Link>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </section>
  );
}

function SummaryCards({
  status,
  onRefresh,
}: {
  status: CacheStatus | null;
  onRefresh: () => void;
}) {
  return (
    <Section title="Status">
      <div className="mb-3 flex justify-end">
        <button
          type="button"
          onClick={onRefresh}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100"
        >
          Refresh
        </button>
      </div>
      {!status ? (
        <p className="text-xs text-neutral-500">Loading cache status…</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Enabled"
            value={status.enabled ? "yes" : "no"}
            tone={status.enabled ? "pass" : "warning"}
          />
          <StatCard label="Backend" value={status.backend} />
          <StatCard label="Keys" value={status.stats.keys} />
          <StatCard label="Hits" value={status.stats.hits} tone="pass" />
          <StatCard label="Misses" value={status.stats.misses} />
          <StatCard label="Dashboard TTL (s)" value={status.ttl.dashboard} />
          <StatCard label="Market TTL (s)" value={status.ttl.market} />
          <StatCard label="Collection TTL (s)" value={status.ttl.collection} />
        </div>
      )}
    </Section>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "pass" | "warning";
}) {
  const toneClass =
    tone === "warning" ? "text-amber-400" : tone === "pass" ? "text-emerald-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function ClearCacheSection({ onCleared }: { onCleared: () => void }) {
  const [prefix, setPrefix] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CacheClearResponse | null>(null);

  const confirmSatisfied = confirmText === CONFIRM_PHRASE;

  async function handleClear() {
    if (!confirmSatisfied) {
      setError(`Type ${CONFIRM_PHRASE} to confirm.`);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const data = await clearCache({
        prefix: prefix.trim() ? prefix.trim() : null,
        confirm: confirmText,
      });
      setResult(data);
      setConfirmText("");
      onCleared();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to clear cache.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section title="Clear cache">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-neutral-400">
          Prefix (optional - leave blank to clear all)
          <input
            type="text"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            placeholder="e.g. dashboard"
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-neutral-400">
          Type <span className="font-mono text-neutral-200">{CONFIRM_PHRASE}</span> to confirm
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100"
          />
        </label>
        <button
          type="button"
          onClick={handleClear}
          disabled={pending}
          className="rounded bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
        >
          {pending ? "Clearing…" : "Clear cache"}
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 rounded border border-emerald-900/50 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-300">
          Cleared {result.prefix ? `prefix "${result.prefix}"` : "all cache keys"}
          {result.deleted_count !== null ? ` - ${result.deleted_count} key(s) deleted.` : "."}
        </div>
      )}
    </Section>
  );
}

function HelpfulPrefixes() {
  return (
    <Section title="Helpful prefixes">
      <div className="flex flex-wrap gap-2">
        {HELPFUL_PREFIXES.map((p) => (
          <span
            key={p}
            className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 font-mono text-xs text-neutral-400"
          >
            {p}
          </span>
        ))}
      </div>
    </Section>
  );
}
