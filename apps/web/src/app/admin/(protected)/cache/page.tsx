"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { ActionButton } from "@/components/ui/ActionButton";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type CacheClearResponse,
  type CacheStatus,
  clearCache,
  fetchCacheStatus,
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
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader
          title="Cache"
          description="Short-lived cache for dashboard and market read endpoints."
        />

        {unauthorized && (
          <AdminSessionExpired />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            {error && (
              <div className="rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
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
    <section className="panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">{title}</h2>
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
        <ActionButton variant="default" onClick={onRefresh}>
          Refresh
        </ActionButton>
      </div>
      {!status ? (
        <p className="text-xs text-text-muted">Loading cache status…</p>
      ) : (
        <StatGrid>
          <StatCard
            label="Enabled"
            value={status.enabled ? "yes" : "no"}
            tone={status.enabled ? "good" : "bad"}
          />
          <StatCard label="Backend" value={status.backend} />
          <StatCard label="Keys" value={status.stats.keys} />
          <StatCard label="Hits" value={status.stats.hits} tone="good" />
          <StatCard label="Misses" value={status.stats.misses} />
          <StatCard label="Dashboard TTL (s)" value={status.ttl.dashboard} />
          <StatCard label="Market TTL (s)" value={status.ttl.market} />
          <StatCard label="Collection TTL (s)" value={status.ttl.collection} />
        </StatGrid>
      )}
    </Section>
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
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Prefix (optional - leave blank to clear all)
          <input
            type="text"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            placeholder="e.g. dashboard"
            className={FILTER_INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Type <span className="mono text-text-primary">{CONFIRM_PHRASE}</span> to confirm
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className={FILTER_INPUT_CLASS}
          />
        </label>
        <ActionButton variant="danger" onClick={handleClear} disabled={pending}>
          {pending ? "Clearing…" : "Clear cache"}
        </ActionButton>
      </div>

      {error && (
        <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 rounded-control border border-signal-green/40 bg-signal-green/10 px-3 py-2 text-xs text-signal-green">
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
            className="rounded-control border border-border-default bg-bg-surface px-2 py-1 font-mono text-xs text-text-secondary"
          >
            {p}
          </span>
        ))}
      </div>
    </Section>
  );
}
