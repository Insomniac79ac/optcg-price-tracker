"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/StateBlocks";
import type { CollectorActivityEvent, CollectorNote } from "@/lib/api";
import { createCollectorNote } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ActionButton } from "./ActionButton";

/** Card-detail notes/activity panel. Notes and activity are two distinct,
 * already-existing resources (POST /collector/notes, GET /collector/
 * activity) - shown side by side here, not merged into one feed. */
export function CardActivityPanel({
  cardId,
  notes,
  activity,
  onNoteAdded,
}: {
  cardId: number;
  notes: CollectorNote[];
  activity: CollectorActivityEvent[];
  onNoteAdded: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitNote(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createCollectorNote({ note_type: "card", card_id: cardId, body: draft.trim() });
      setDraft("");
      onNoteAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
      <div>
        <h2 className="mb-2 text-sm font-semibold text-text-primary">Notes</h2>
        {notes.length === 0 ? (
          <EmptyState variant="inline">No notes yet.</EmptyState>
        ) : (
          <div className="mb-3 space-y-2">
            {notes.map((note) => (
              <div key={note.id} className="rounded-control border border-border-default bg-bg-page p-2 text-xs">
                {note.title && <div className="mb-0.5 font-medium text-text-primary">{note.title}</div>}
                <div className="text-text-secondary">{note.body}</div>
                <div className="mono mt-1 text-[11px] text-text-faint">
                  {formatDateTime(note.created_at)}
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={submitNote} className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Add a note about this card…"
            className="w-full rounded-control border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
          />
          <ActionButton type="submit" disabled={saving || !draft.trim()}>
            {saving ? "Saving…" : "Add"}
          </ActionButton>
        </form>
        {error && <p className="mt-1 text-[11px] text-signal-red">{error}</p>}
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Activity</h2>
          <Link href="/activity" className="text-xs text-sky-400 hover:text-sky-300">
            View activity →
          </Link>
        </div>
        {activity.length === 0 ? (
          <EmptyState variant="inline">No recent activity for this card.</EmptyState>
        ) : (
          <div className="space-y-2">
            {activity.map((event) => (
              <div key={event.id} className="rounded-control border border-border-default bg-bg-page p-2 text-xs">
                <div className="font-medium text-text-primary">{event.title}</div>
                {event.message && <div className="text-text-secondary">{event.message}</div>}
                <div className="mono mt-1 text-[11px] text-text-faint">
                  {formatDateTime(event.created_at)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
