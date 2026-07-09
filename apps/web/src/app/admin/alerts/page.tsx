"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AlertStatusBadge } from "@/components/AlertStatusBadge";
import { AppHeader } from "@/components/AppHeader";
import {
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
      .catch(() => {
        if (cancelled) return;
        setEventsStatus("error");
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
      .catch(() => setRulesStatus("error"));
  }, []);

  async function toggleActive(rule: AlertRule) {
    setPendingRuleId(rule.id);
    setRuleActionError(null);
    try {
      const updated = await updateAlertRule(rule.id, {
        is_active: !rule.is_active,
      });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch {
      setRuleActionError("Failed to update rule.");
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
    } catch {
      setRuleActionError("Failed to update threshold.");
    } finally {
      setPendingRuleId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Alerts</h1>
        </div>

        <section className="mb-8">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-neutral-200">
              Alert events
            </h2>
            {eventsStatus === "ready" && (
              <span className="text-sm text-neutral-500">
                {eventsTotal} event{eventsTotal === 1 ? "" : "s"}
              </span>
            )}
          </div>

          <div className="mb-3 flex gap-1">
            {EVENT_STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setEventsStatusFilter(f.value)}
                className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                  eventsStatusFilter === f.value
                    ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                    : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {eventsStatus === "loading" && (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
              Loading alert events…
            </div>
          )}

          {eventsStatus === "error" && (
            <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
              Failed to load alert events from the API. Is the backend
              running?
            </div>
          )}

          {eventsStatus === "ready" && events.length === 0 && (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
              No alert events found.
            </div>
          )}

          {eventsStatus === "ready" && events.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Event type</th>
                    <th className="px-3 py-2 font-medium">Card</th>
                    <th className="px-3 py-2 font-medium">Source</th>
                    <th className="px-3 py-2 font-medium">Title</th>
                    <th className="px-3 py-2 font-medium">Sent</th>
                    <th className="px-3 py-2 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr
                      key={event.id}
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-3 py-2">
                        <AlertStatusBadge status={event.status} />
                      </td>
                      <td className="px-3 py-2 text-neutral-300">
                        {event.event_type}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {event.card_id ? (
                          <Link
                            href={`/cards/${event.card_id}`}
                            className="hover:text-sky-400"
                          >
                            {event.card_name ??
                              event.card_code ??
                              `#${event.card_id}`}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {event.source_name ?? "—"}
                      </td>
                      <td className="max-w-sm px-3 py-2">
                        <span
                          className="block truncate text-neutral-200"
                          title={event.title}
                        >
                          {event.title}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {formatDateTime(event.sent_at)}
                      </td>
                      <td className="max-w-xs px-3 py-2">
                        {event.error_message ? (
                          <span
                            className="block truncate text-xs text-rose-300"
                            title={event.error_message}
                          >
                            {event.error_message}
                          </span>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold text-neutral-200">
            Alert rules
          </h2>

          {ruleActionError && (
            <div className="mb-3 rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">
              {ruleActionError}
            </div>
          )}

          {rulesStatus === "loading" && (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
              Loading alert rules…
            </div>
          )}

          {rulesStatus === "error" && (
            <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
              Failed to load alert rules from the API. Is the backend
              running?
            </div>
          )}

          {rulesStatus === "ready" && rules.length === 0 && (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
              No alert rules configured.
            </div>
          )}

          {rulesStatus === "ready" && rules.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Rule type</th>
                    <th className="px-3 py-2 font-medium">Source</th>
                    <th className="px-3 py-2 font-medium">Price type</th>
                    <th className="px-3 py-2 font-medium">Threshold %</th>
                    <th className="px-3 py-2 font-medium">Active</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((rule) => (
                    <tr
                      key={rule.id}
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-3 py-2 font-medium text-neutral-100">
                        {rule.name}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {rule.rule_type}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {rule.source_name ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">
                        {rule.price_type ?? "—"}
                      </td>
                      <td className="px-3 py-2">
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
                          className="w-20 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 disabled:opacity-50"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <button
                          onClick={() => toggleActive(rule)}
                          disabled={pendingRuleId === rule.id}
                          className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset disabled:opacity-50 ${
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
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
