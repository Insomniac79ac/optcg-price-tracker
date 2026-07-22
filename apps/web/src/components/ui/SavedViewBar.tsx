"use client";

import { useEffect, useState } from "react";

import {
  AdminAuthRequiredError,
  clearDefaultSavedView,
  createSavedView,
  deleteSavedView,
  fetchSavedViews,
  setDefaultSavedView,
  updateSavedView,
  markSavedViewUsed,
  type SavedView,
  type SavedViewScope,
} from "@/lib/api";
import { ActionButton } from "./ActionButton";
import { ConfirmActionModal } from "./ConfirmActionModal";
import { ManageSavedViewsModal } from "./ManageSavedViewsModal";
import { SavedViewPill } from "./SavedViewPill";
import { SaveViewModal, type SaveViewFormValues } from "./SaveViewModal";

/** Per-page saved-views integration point. Each page supplies its own
 * `currentFilters` (a plain object built from its existing filter useState
 * variables - see docs/interface_design_system.md "Saved views") and an
 * `onApply` that calls the matching setters. This component owns fetching/
 * saving/deleting the SavedView rows for this route_path+view_type and
 * never touches the page's own state beyond calling onApply. */
export function SavedViewBar({
  routePath,
  viewType,
  scope,
  currentFilters,
  onApply,
}: {
  routePath: string;
  viewType: string;
  scope: SavedViewScope;
  currentFilters: Record<string, unknown>;
  onApply: (filters: Record<string, unknown>) => void;
}) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "signed-out">("loading");
  const [activeViewId, setActiveViewId] = useState<number | null>(null);

  const [saveOpen, setSaveOpen] = useState(false);
  const [editingView, setEditingView] = useState<SavedView | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [manageOpen, setManageOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SavedView | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);

  function load() {
    setStatus("loading");
    fetchSavedViews({ route_path: routePath, view_type: viewType })
      .then((res) => {
        setViews(res.items);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setStatus("signed-out");
        else setStatus("error");
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routePath, viewType]);

  const activeView = views.find((v) => v.id === activeViewId) ?? null;

  function applyView(view: SavedView) {
    setActiveViewId(view.id);
    onApply(view.filters_json ?? {});
    markSavedViewUsed(view.id).catch(() => {});
  }

  async function handleSaveNew(values: SaveViewFormValues) {
    setSaving(true);
    setSaveError(null);
    try {
      const created = await createSavedView({
        name: values.name,
        description: values.description || null,
        route_path: routePath,
        view_type: viewType,
        scope,
        filters_json: currentFilters,
        density: values.density,
        is_default: values.is_default,
        pinned: values.pinned,
      });
      setSaveOpen(false);
      setActiveViewId(created.id);
      load();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save this view.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveEdit(values: SaveViewFormValues) {
    if (!editingView) return;
    setSaving(true);
    setSaveError(null);
    try {
      await updateSavedView(editingView.id, {
        name: values.name,
        description: values.description || null,
        density: values.density,
        pinned: values.pinned,
        is_default: values.is_default,
      });
      setEditingView(null);
      load();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to update this view.");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateCurrent() {
    if (!activeView) return;
    await updateSavedView(activeView.id, { filters_json: currentFilters });
    load();
  }

  async function handleSetDefault() {
    if (!activeView) return;
    await setDefaultSavedView(activeView.id);
    load();
  }

  async function handleClearDefault() {
    await clearDefaultSavedView(routePath, viewType);
    load();
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    await deleteSavedView(deleteTarget.id);
    if (activeViewId === deleteTarget.id) setActiveViewId(null);
    setDeleteTarget(null);
    setManageOpen(false);
    load();
  }

  if (status === "signed-out") {
    return (
      <p className="mb-3 text-xs text-text-muted">
        Sign in to use saved views on this page.
      </p>
    );
  }

  if (status === "error") {
    return <p className="mb-3 text-xs text-text-muted">Saved views are unavailable right now.</p>;
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {activeView && <SavedViewPill name={activeView.name} />}

      <select
        value={activeViewId ?? ""}
        onChange={(e) => {
          const id = Number(e.target.value);
          const view = views.find((v) => v.id === id);
          if (view) applyView(view);
        }}
        className="rounded-control border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
      >
        <option value="">
          {status === "loading" ? "Loading saved views…" : "Saved views…"}
        </option>
        {views.map((view) => (
          <option key={view.id} value={view.id}>
            {view.name}
            {view.is_default ? " (default)" : ""}
          </option>
        ))}
      </select>

      <ActionButton onClick={() => setSaveOpen(true)}>Save current view</ActionButton>

      {/* Secondary view actions - compact on mobile behind a toggle so this
          row doesn't wrap to several lines above every filterable page. */}
      <button
        type="button"
        onClick={() => setMoreOpen((v) => !v)}
        aria-expanded={moreOpen}
        className="rounded-control border border-border-default px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary sm:hidden"
      >
        {moreOpen ? "Less…" : "More…"}
      </button>
      <div className={`${moreOpen ? "flex" : "hidden"} flex-wrap items-center gap-2 sm:flex`}>
        <ActionButton disabled={!activeView} onClick={handleUpdateCurrent}>
          Update current view
        </ActionButton>
        <ActionButton disabled={!activeView || activeView.is_default} onClick={handleSetDefault}>
          Set default
        </ActionButton>
        <ActionButton onClick={handleClearDefault}>Clear default</ActionButton>
        <ActionButton onClick={() => setManageOpen(true)}>Manage views</ActionButton>
      </div>

      <SaveViewModal
        open={saveOpen}
        title="Save current view"
        saving={saving}
        error={saveError}
        onSave={handleSaveNew}
        onCancel={() => {
          setSaveOpen(false);
          setSaveError(null);
        }}
      />

      {editingView && (
        <SaveViewModal
          open
          title="Edit saved view"
          initialValues={{
            name: editingView.name,
            description: editingView.description ?? "",
            pinned: editingView.pinned,
            is_default: editingView.is_default,
            density: editingView.density,
          }}
          saving={saving}
          error={saveError}
          onSave={handleSaveEdit}
          onCancel={() => {
            setEditingView(null);
            setSaveError(null);
          }}
        />
      )}

      <ManageSavedViewsModal
        open={manageOpen}
        views={views}
        onClose={() => setManageOpen(false)}
        onEdit={(view) => setEditingView(view)}
        onDelete={(view) => setDeleteTarget(view)}
        onSetDefault={(view) => setDefaultSavedView(view.id).then(load)}
        onClearDefault={() => handleClearDefault()}
        onTogglePinned={(view) => updateSavedView(view.id, { pinned: !view.pinned }).then(load)}
      />

      <ConfirmActionModal
        open={deleteTarget !== null}
        title="Delete saved view"
        description={deleteTarget ? `Delete "${deleteTarget.name}"? This cannot be undone.` : undefined}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
