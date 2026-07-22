"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import { ActionButton } from "./ActionButton";

interface AffectedRecord {
  label: string;
  value: ReactNode;
}

/** Two-tier confirmation modal for real/destructive admin actions (design
 * brief §6). Without `confirmPhrase` it's a plain Confirm/Cancel dialog
 * (replaces ad hoc `window.confirm()` calls). With `confirmPhrase` set
 * (e.g. "MERGE", "RUN", "RESTORE", "IMPORT") the confirm button stays
 * disabled until the user types that exact word - one component, two
 * configurations, rather than a separate modal for each. */
export function ConfirmActionModal({
  open,
  title,
  description,
  affectedRecords,
  confirmPhrase,
  confirmLabel = "Confirm",
  pending = false,
  error,
  onConfirm,
  onCancel,
  children,
  disableConfirm = false,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  affectedRecords?: AffectedRecord[];
  confirmPhrase?: string;
  confirmLabel?: string;
  pending?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  /** Extra caller-owned gate on top of the pending/typed-phrase checks -
   * e.g. card-duplicates' "approve low-confidence merge" checkbox. */
  disableConfirm?: boolean;
}) {
  const [typed, setTyped] = useState("");

  if (!open) return null;

  const canConfirm =
    !pending && !disableConfirm && (!confirmPhrase || typed.trim() === confirmPhrase);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-5">
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-text-primary">{title}</h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-xs font-medium text-text-muted hover:text-text-primary"
          >
            Close
          </button>
        </div>

        {description && <p className="mb-3 text-sm text-text-secondary">{description}</p>}

        {affectedRecords && affectedRecords.length > 0 && (
          <div className="mb-3 panel p-3">
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
              Affected records
            </div>
            <div className="grid grid-cols-2 gap-1 text-xs text-text-secondary sm:grid-cols-3">
              {affectedRecords.map((r) => (
                <div key={r.label}>
                  {r.label}: <span className="mono tabular text-text-primary">{r.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {children && <div className="mb-3">{children}</div>}

        {error && (
          <div className="mb-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {confirmPhrase && (
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={`Type ${confirmPhrase} to confirm`}
              className="w-48 rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
            />
          )}
          <ActionButton variant="danger" disabled={!canConfirm} onClick={onConfirm}>
            {pending ? "Working…" : confirmLabel}
          </ActionButton>
          <ActionButton variant="default" disabled={pending} onClick={onCancel}>
            Cancel
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
