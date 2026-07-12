"use client";

import { useState } from "react";

import type { CollectorTag } from "@/lib/api";

import { CollectorTagBadge } from "./CollectorTagBadge";

export function CollectionItemTagsCell({
  assigned,
  available,
  onAssign,
  onUnassign,
}: {
  assigned: CollectorTag[];
  available: CollectorTag[];
  onAssign: (tagId: number) => Promise<void>;
  onUnassign: (tagId: number) => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const assignedIds = new Set(assigned.map((t) => t.id));
  const options = available.filter((t) => !assignedIds.has(t.id));

  async function handleAdd(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = Number(e.target.value);
    e.target.value = "";
    if (!id) return;
    setPending(true);
    try {
      await onAssign(id);
    } finally {
      setPending(false);
    }
  }

  async function handleRemove(tagId: number) {
    setPending(true);
    try {
      await onUnassign(tagId);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {assigned.map((tag) => (
        <CollectorTagBadge key={tag.id} tag={tag} onRemove={() => handleRemove(tag.id)} />
      ))}
      {options.length > 0 && (
        <select
          value=""
          onChange={handleAdd}
          disabled={pending}
          className="rounded border border-neutral-800 bg-neutral-950 px-1 py-0.5 text-[10px] text-neutral-500 disabled:opacity-50"
        >
          <option value="">+ tag</option>
          {options.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
