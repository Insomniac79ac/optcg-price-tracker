"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
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
  ok: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  skipped: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
  error: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
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
        <PageHeader
          title="Data retention"
          description="Review and prune old high-volume data safely."
          actions={<AdminLogoutButton />}
        />

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
    <section className="panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">{title}</h2>
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
        <div className="mb-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}
      <DataTableShell isEmpty={!policies || policies.length === 0} emptyLabel={!policies ? "Loading policy…" : "No prunable tables configured."}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Table</th>
              <th>Retention days</th>
              <th>Mode</th>
              <th>Protected records</th>
              <th>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {policies?.map((p) => (
              <tr key={p.table}>
                <td className="mono text-text-secondary">{p.table}</td>
                <td className="mono tabular">{p.retention_days}</td>
                <td className="mono text-text-secondary">{p.mode}</td>
                <td className="text-text-secondary">{p.protected_records}</td>
                <td>
                  <Badge
                    label={p.enabled ? "enabled" : "disabled"}
                    className={
                      p.enabled
                        ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30"
                        : "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30"
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTableShell>
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
          <span className="text-xs text-text-muted">Loading tables…</span>
        )}
        {allTables.map((table) => (
          <label
            key={table}
            className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1 text-xs text-text-secondary"
          >
            <input
              type="checkbox"
              checked={selectedTables.has(table)}
              onChange={() => toggleTable(table)}
              className="rounded border-border-default bg-bg-page"
            />
            <span className="font-mono">{table}</span>
          </label>
        ))}
      </div>
      <p className="mb-3 text-[11px] text-text-muted">
        Leave all unchecked to evaluate every prunable table.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setError(null);
            }}
            className="rounded border-border-default bg-bg-page"
          />
          Dry run
        </label>

        {!dryRun && (
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            Type <span className="font-mono text-text-primary">{CONFIRM_PHRASE}</span> to confirm:
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
            />
          </label>
        )}

        <ActionButton
          variant={dryRun ? "dry-run" : "danger"}
          onClick={handleRun}
          disabled={pending || !confirmSatisfied}
        >
          {pending ? "Working…" : dryRun ? "Preview prune" : "Run prune"}
        </ActionButton>
      </div>

      {error && (
        <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {summary && (
        <StatGrid>
          <StatCard label="Tables checked" value={summary.tables_checked} />
          <StatCard label="Would delete" value={summary.total_rows_would_delete} />
          <StatCard label="Deleted" value={summary.total_rows_deleted} />
          <StatCard
            label="Warnings"
            value={summary.warnings}
            tone={summary.warnings > 0 ? "bad" : "neutral"}
          />
        </StatGrid>
      )}

      {results && (
        <div className="mt-4">
          <DataTableShell isEmpty={results.length === 0} emptyLabel="No prune results.">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Would delete</th>
                  <th>Deleted</th>
                  <th>Status</th>
                  <th>Warning</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.table}>
                    <td className="mono text-text-secondary">{r.table}</td>
                    <td className="mono tabular">{r.rows_would_delete}</td>
                    <td className="mono tabular">{r.rows_deleted}</td>
                    <td>
                      <Badge label={r.status} className={STATUS_STYLES[r.status] ?? STATUS_STYLES.skipped} />
                    </td>
                    <td className="text-text-secondary">{r.warning ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableShell>
        </div>
      )}
    </Section>
  );
}

function SafetyNotes() {
  return (
    <Section title="Safety notes">
      <ul className="list-disc space-y-1 pl-4 text-xs text-text-secondary">
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

