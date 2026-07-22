"use client";

import type { SavedView } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { ActionButton } from "./ActionButton";
import { EmptyState } from "@/components/StateBlocks";

/** Lists every saved view for the current route_path+view_type: pin/
 * default toggles, last used, usage count, edit, delete. Deletion is
 * confirmed by the caller (see SavedViewBar, which wraps delete in
 * ConfirmActionModal) - this component just exposes the action. */
export function ManageSavedViewsModal({
  open,
  views,
  onClose,
  onEdit,
  onDelete,
  onSetDefault,
  onClearDefault,
  onTogglePinned,
}: {
  open: boolean;
  views: SavedView[];
  onClose: () => void;
  onEdit: (view: SavedView) => void;
  onDelete: (view: SavedView) => void;
  onSetDefault: (view: SavedView) => void;
  onClearDefault: (view: SavedView) => void;
  onTogglePinned: (view: SavedView) => void;
}) {
  useEscapeKey(open, onClose);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-5">
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-text-primary">Manage saved views</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-medium text-text-muted hover:text-text-primary"
          >
            Close
          </button>
        </div>

        {views.length === 0 ? (
          <EmptyState>No saved views for this page yet.</EmptyState>
        ) : (
          <div className="divide-y divide-border-muted">
            {views.map((view) => (
              <div key={view.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium text-text-primary">{view.name}</span>
                    {view.is_default && (
                      <span className="badge bg-accent-gold/10 text-accent-gold ring-1 ring-inset ring-accent-gold/30">
                        default
                      </span>
                    )}
                    {view.pinned && (
                      <span className="badge bg-signal-purple/10 text-signal-purple ring-1 ring-inset ring-signal-purple/30">
                        pinned
                      </span>
                    )}
                  </div>
                  {view.description && (
                    <div className="text-xs text-text-secondary">{view.description}</div>
                  )}
                  <div className="mono text-[11px] text-text-muted">
                    Used {view.usage_count}× · Last used {formatDateTime(view.last_used_at)}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <ActionButton onClick={() => onTogglePinned(view)}>
                    {view.pinned ? "Unpin" : "Pin"}
                  </ActionButton>
                  <ActionButton
                    onClick={() => (view.is_default ? onClearDefault(view) : onSetDefault(view))}
                  >
                    {view.is_default ? "Clear default" : "Set default"}
                  </ActionButton>
                  <ActionButton onClick={() => onEdit(view)}>Edit</ActionButton>
                  <ActionButton variant="danger" onClick={() => onDelete(view)}>
                    Delete
                  </ActionButton>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
