"use client";

import { useState } from "react";

import type { SavedViewDensity } from "@/lib/api";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { ActionButton } from "./ActionButton";

export interface SaveViewFormValues {
  name: string;
  description: string;
  pinned: boolean;
  is_default: boolean;
  density: SavedViewDensity;
}

const EMPTY_VALUES: SaveViewFormValues = {
  name: "",
  description: "",
  pinned: false,
  is_default: false,
  density: "compact",
};

/** Save/edit form for a saved view - name, description, pinned/default
 * checkboxes, density selector. Not a confirm-phrase gate (see
 * ConfirmActionModal for that pattern) - just a small form in the same
 * modal chrome (rounded-modal, bg-bg-elevated). */
export function SaveViewModal({
  open,
  title = "Save current view",
  initialValues,
  saving = false,
  error,
  onSave,
  onCancel,
}: {
  open: boolean;
  title?: string;
  initialValues?: Partial<SaveViewFormValues>;
  saving?: boolean;
  error?: string | null;
  onSave: (values: SaveViewFormValues) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<SaveViewFormValues>({
    ...EMPTY_VALUES,
    ...initialValues,
  });

  useEscapeKey(open, onCancel);

  if (!open) return null;

  function update<K extends keyof SaveViewFormValues>(key: K, value: SaveViewFormValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  const canSave = values.name.trim().length > 0 && !saving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-modal border border-border-default bg-bg-elevated p-5">
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

        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs uppercase tracking-wide text-text-secondary">
              Name
            </span>
            <input
              value={values.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="e.g. Review Buy"
              autoFocus
              className="w-full rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs uppercase tracking-wide text-text-secondary">
              Description
            </span>
            <input
              value={values.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="Optional"
              className="w-full rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs uppercase tracking-wide text-text-secondary">
              Density
            </span>
            <select
              value={values.density}
              onChange={(e) => update("density", e.target.value as SavedViewDensity)}
              className="w-full rounded-control border border-border-default bg-bg-surface px-2 py-1 text-sm text-text-primary"
            >
              <option value="compact">Compact</option>
              <option value="comfortable">Comfortable</option>
            </select>
          </label>

          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1.5 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={values.pinned}
                onChange={(e) => update("pinned", e.target.checked)}
              />
              Pin to dashboard
            </label>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={values.is_default}
                onChange={(e) => update("is_default", e.target.checked)}
              />
              Set as default for this page
            </label>
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
            {error}
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <ActionButton variant="primary" disabled={!canSave} onClick={() => onSave(values)}>
            {saving ? "Saving…" : "Save"}
          </ActionButton>
          <ActionButton disabled={saving} onClick={onCancel}>
            Cancel
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
