"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AlertStatusBadge } from "@/components/AlertStatusBadge";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  type AlertEvent,
  type AlertRule,
  fetchAlertEvents,
  fetchAlertRules,
  updateAlertRule,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const EVENT_STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
  { value: "skipped_duplicate", label: "Skipped" },
];

export default function AlertsPage() {
  const [unauthorized, setUnauthorized] = useState(false);

  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [eventsStatusFilter, setEventsStatusFilter] = useState("");
  const [eventsStatus, setEventsStatus] = useState<
    "loading" | "error" | "ready"
  >("loading");

  const [rules, setRules] = useState<AlertRule[]>([]);
  const [rulesStatus, setRulesStatus] = useState<
    "loading" | "error" | "ready"
  >("loading");
  const [ruleDrafts, setRuleDrafts] = useState<Record<number, string>>({});
  const [pendingRuleId, setPendingRuleId] = useState<number | null>(null);
  const [ruleActionError, setRuleActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchAlertEvents({ status: eventsStatusFilter || undefined, limit: 100 })
      .then((data) => {
        if (cancelled) return;
        setEvents(data.items);
        setEventsTotal(data.total);
        setEventsStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setEventsStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [eventsStatusFilter]);

  useEffect(() => {
    fetchAlertRules()
      .then((data) => {
        setRules(data);
        setRuleDrafts(
          Object.fromEntries(
            data.map((r) => [
              r.id,
              r.threshold_pct !== null ? String(r.threshold_pct) : "",
            ]),
          ),
        );
        setRulesStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setRulesStatus("error");
      });
  }, []);

  async function toggleActive(rule: AlertRule) {
    setPendingRuleId(rule.id);
    setRuleActionError(null);
    try {
      const updated = await updateAlertRule(rule.id, {
        is_active: !rule.is_active,
      });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setRuleActionError("Failed to update rule.");
    } finally {
      setPendingRuleId(null);
    }
  }

  async function saveThreshold(rule: AlertRule) {
    const raw = ruleDrafts[rule.id];
    const parsed = raw === "" || raw === undefined ? null : Number(raw);
    if (parsed === null || Number.isNaN(parsed) || parsed === rule.threshold_pct) {
      return;
    }

    setPendingRuleId(rule.id);
    setRuleActionError(null);
    try {
      const updated = await updateAlertRule(rule.id, { threshold_pct: parsed });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setRuleActionError("Failed to update threshold.");
    } finally {
      setPendingRuleId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader title="Alerts" actions={<AdminLogoutButton />} />

        {unauthorized && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {!unauthorized && (
          <>
            <section className="mb-8">
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-text-primary">Alert events</h2>
                {eventsStatus === "ready" && (
                  <span className="text-sm text-text-muted">
                    {eventsTotal} event{eventsTotal === 1 ? "" : "s"}
                  </span>
                )}
              </div>

              <div className="mb-3 flex gap-1">
                {EVENT_STATUS_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    onClick={() => setEventsStatusFilter(f.value)}
                    className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                      eventsStatusFilter === f.value
                        ? "bg-accent-gold text-black/80 ring-accent-gold"
                        : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              {eventsStatus === "loading" && <LoadingState>Loading alert events…</LoadingState>}

              {eventsStatus === "error" && (
                <ErrorState>Failed to load alert events from the API. Is the backend running?</ErrorState>
              )}

              {eventsStatus === "ready" && (
                <DataTableShell isEmpty={events.length === 0} emptyLabel="No alert events found.">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Event type</th>
                        <th>Card</th>
                        <th>Source</th>
                        <th>Title</th>
                        <th>Sent</th>
                        <th>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((event) => (
                        <tr key={event.id}>
                          <td>
                            <AlertStatusBadge status={event.status} />
                          </td>
                          <td className="text-text-secondary">{event.event_type}</td>
                          <td className="text-text-secondary">
                            {event.card_id ? (
                              <Link href={`/cards/${event.card_id}`} className="hover:text-sky-400">
                                {event.card_name ?? event.card_code ?? `#${event.card_id}`}
                              </Link>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="text-text-secondary">{event.source_name ?? "—"}</td>
                          <td className="max-w-sm">
                            <span className="block truncate text-text-primary" title={event.title}>
                              {event.title}
                            </span>
                          </td>
                          <td className="mono text-xs text-text-muted">{formatDateTime(event.sent_at)}</td>
                          <td className="max-w-xs">
                            {event.error_message ? (
                              <span className="block truncate text-xs text-signal-red" title={event.error_message}>
                                {event.error_message}
                              </span>
                            ) : (
                              <span className="text-text-faint">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </DataTableShell>
              )}
            </section>

            <section>
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Alert rules</h2>

              {ruleActionError && (
                <div className="mb-3 rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">
                  {ruleActionError}
                </div>
              )}

              {rulesStatus === "loading" && <LoadingState>Loading alert rules…</LoadingState>}

              {rulesStatus === "error" && (
                <ErrorState>Failed to load alert rules from the API. Is the backend running?</ErrorState>
              )}

              {rulesStatus === "ready" && (
                <DataTableShell isEmpty={rules.length === 0} emptyLabel="No alert rules configured.">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Rule type</th>
                        <th>Source</th>
                        <th>Price type</th>
                        <th>Threshold %</th>
                        <th>Active</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rules.map((rule) => (
                        <tr key={rule.id}>
                          <td className="font-medium text-text-primary">{rule.name}</td>
                          <td className="text-text-secondary">{rule.rule_type}</td>
                          <td className="text-text-secondary">{rule.source_name ?? "—"}</td>
                          <td className="text-text-secondary">{rule.price_type ?? "—"}</td>
                          <td>
                            <input
                              value={ruleDrafts[rule.id] ?? ""}
                              onChange={(e) =>
                                setRuleDrafts((prev) => ({
                                  ...prev,
                                  [rule.id]: e.target.value,
                                }))
                              }
                              onBlur={() => saveThreshold(rule)}
                              disabled={pendingRuleId === rule.id}
                              className={`w-20 ${FILTER_INPUT_CLASS} disabled:opacity-50`}
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={() => toggleActive(rule)}
                              disabled={pendingRuleId === rule.id}
                              className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors disabled:opacity-50 ${
                                rule.is_active
                                  ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30 hover:bg-emerald-500/25"
                                  : "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30 hover:bg-neutral-500/25"
                              }`}
                            >
                              {rule.is_active ? "Active" : "Inactive"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </DataTableShell>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
