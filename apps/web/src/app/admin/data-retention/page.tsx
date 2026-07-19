"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  type DataRetentionPolicy,
  type DataRetentionPruneResult,
  fetchDataRetentionPolicy,
  getAdminToken,
  pruneDataRetention,
} from "@/lib/api";

const CONFIRM_PHRASE = "PRUNE";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  skipped: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  error: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

export default function DataRetentionPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [policies, setPolicies] = useState<DataRetentionPolicy[] | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);

  function loadPolicies() {
    fetchDataRetentionPolicy()
      .then((data) => {
        setPolicies(data.policies);
        setPolicyError(null);
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) {
          setUnauthorized(true);
        } else {
          setPolicyError(err instanceof Error ? err.message : "Failed to load policy.");
        }
      });
  }

  useEffect(() => {
    setUnauthorized(!getAdminToken());
    loadPolicies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Data retention</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Review and prune old high-volume data safely.
        </p>

        {unauthorized && (
          <AdminAuthGate
            onTokenSaved={() => {
              setUnauthorized(false);
              loadPolicies();
            }}
          />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            <PolicySection policies={policies} error={policyError} />
            <PruneSection policies={policies} />
            <SafetyNotes />

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/performance"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Performance
              </Link>
              <Link
                href="/admin/cache"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Cache
              </Link>
              <Link
                href="/admin/job-locks"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Job locks
              </Link>
              <Link
                href="/admin/file-jobs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                File jobs
              </Link>
              <Link
                href="/admin/logs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                App logs
              </Link>
              <Link
                href="/admin/actions"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Admin actions
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

function PolicySection({
  policies,
  error,
}: {
  policies: DataRetentionPolicy[] | null;
  error: string | null;
}) {
  return (
    <Section title="Retention policy">
      {error && (
        <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-neutral-800 bg-neutral-950 text-left text-[11px] uppercase tracking-wide text-neutral-500">
              <th className="px-3 py-2 font-medium">Table</th>
              <th className="px-3 py-2 font-medium">Retention days</th>
              <th className="px-3 py-2 font-medium">Mode</th>
              <th className="px-3 py-2 font-medium">Protected records</th>
              <th className="px-3 py-2 font-medium">Enabled</th>
            </tr>
          </thead>
          <tbody>
            {!policies ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-neutral-500">
                  Loading policy…
                </td>
              </tr>
            ) : policies.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-neutral-500">
                  No prunable tables configured.
                </td>
              </tr>
            ) : (
              policies.map((p) => (
                <tr
                  key={p.table}
                  className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                >
                  <td className="px-3 py-2 font-mono text-neutral-300">{p.table}</td>
                  <td className="px-3 py-2 text-neutral-300">{p.retention_days}</td>
                  <td className="px-3 py-2 font-mono text-neutral-400">{p.mode}</td>
                  <td className="px-3 py-2 text-neutral-400">{p.protected_records}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                        p.enabled
                          ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
                          : "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30"
                      }`}
                    >
                      {p.enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function PruneSection({ policies }: { policies: DataRetentionPolicy[] | null }) {
  const allTables = policies?.map((p) => p.table) ?? [];
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [dryRun, setDryRun] = useState(true);
  const [confirmText, setConfirmText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DataRetentionPruneResult[] | null>(null);
  const [summary, setSummary] = useState<{
    tables_checked: number;
    total_rows_would_delete: number;
    total_rows_deleted: number;
    warnings: number;
  } | null>(null);

  const confirmSatisfied = dryRun || confirmText === CONFIRM_PHRASE;

  function toggleTable(table: string) {
    setSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(table)) next.delete(table);
      else next.add(table);
      return next;
    });
  }

  async function handleRun() {
    if (!confirmSatisfied) {
      setError(`Type ${CONFIRM_PHRASE} to confirm a real prune.`);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const data = await pruneDataRetention({
        dry_run: dryRun,
        tables: selectedTables.size > 0 ? Array.from(selectedTables) : null,
        confirm: dryRun ? undefined : confirmText,
      });
      setResults(data.results);
      setSummary(data.summary);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to run prune.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section title="Prune old data">
      <div className="mb-3 flex flex-wrap gap-2">
        {allTables.length === 0 && (
          <span className="text-xs text-neutral-500">Loading tables…</span>
        )}
        {allTables.map((table) => (
          <label
            key={table}
            className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-400"
          >
            <input
              type="checkbox"
              checked={selectedTables.has(table)}
              onChange={() => toggleTable(table)}
              className="rounded border-neutral-700 bg-neutral-950"
            />
            <span className="font-mono">{table}</span>
          </label>
        ))}
      </div>
      <p className="mb-3 text-[11px] text-neutral-500">
        Leave all unchecked to evaluate every prunable table.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setError(null);
            }}
            className="rounded border-neutral-700 bg-neutral-950"
          />
          Dry run
        </label>

        {!dryRun && (
          <label className="flex items-center gap-2 text-xs text-neutral-400">
            Type <span className="font-mono text-neutral-200">{CONFIRM_PHRASE}</span> to confirm:
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </label>
        )}

        <button
          type="button"
          onClick={handleRun}
          disabled={pending || !confirmSatisfied}
          className={`rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
            dryRun
              ? "bg-neutral-100 text-neutral-900 hover:bg-white"
              : "bg-rose-600 text-white hover:bg-rose-500"
          }`}
        >
          {pending ? "Working…" : dryRun ? "Preview prune" : "Run prune"}
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      {summary && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Tables checked" value={summary.tables_checked} />
          <StatCard label="Would delete" value={summary.total_rows_would_delete} />
          <StatCard label="Deleted" value={summary.total_rows_deleted} />
          <StatCard label="Warnings" value={summary.warnings} tone="warning" />
        </div>
      )}

      {results && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-neutral-800 bg-neutral-950 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                <th className="px-3 py-2 font-medium">Table</th>
                <th className="px-3 py-2 font-medium">Would delete</th>
                <th className="px-3 py-2 font-medium">Deleted</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Warning</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={r.table}
                  className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                >
                  <td className="px-3 py-2 font-mono text-neutral-300">{r.table}</td>
                  <td className="px-3 py-2 text-neutral-300">{r.rows_would_delete}</td>
                  <td className="px-3 py-2 text-neutral-300">{r.rows_deleted}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                        STATUS_STYLES[r.status] ?? STATUS_STYLES.skipped
                      }`}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-neutral-400">{r.warning ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function SafetyNotes() {
  return (
    <Section title="Safety notes">
      <ul className="list-disc space-y-1 pl-4 text-xs text-neutral-400">
        <li>The latest price observation for every card/source/price type is always protected.</li>
        <li>Open and watching signal events are always protected.</li>
        <li>
          Collector records (cards, collection, wishlist, grading, tags, groups, notes, alert
          rules, dashboard preferences) are never automatically pruned.
        </li>
        <li>
          Take a database backup before running a real (non-dry-run) prune - see{" "}
          <Link
            href="/admin/backup"
            className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Backup &amp; restore
          </Link>
          .
        </li>
      </ul>
    </Section>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "warning";
}) {
  const toneClass = tone === "warning" && value > 0 ? "text-amber-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
