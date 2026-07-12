"use client";

import { useState } from "react";

import type { CollectorGroup } from "@/lib/api";

import { CollectorGroupLabel } from "./CollectorGroupLabel";

export function CollectionItemGroupsCell({
  assigned,
  available,
  onAssign,
  onUnassign,
}: {
  assigned: CollectorGroup[];
  available: CollectorGroup[];
  onAssign: (groupId: number) => Promise<void>;
  onUnassign: (groupId: number) => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const assignedIds = new Set(assigned.map((g) => g.id));
  const options = available.filter((g) => !assignedIds.has(g.id));

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

  async function handleRemove(groupId: number) {
    setPending(true);
    try {
      await onUnassign(groupId);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {assigned.map((group) => (
        <CollectorGroupLabel
          key={group.id}
          group={group}
          onRemove={() => handleRemove(group.id)}
        />
      ))}
      {options.length > 0 && (
        <select
          value=""
          onChange={handleAdd}
          disabled={pending}
          className="rounded border border-neutral-800 bg-neutral-950 px-1 py-0.5 text-[10px] text-neutral-500 disabled:opacity-50"
        >
          <option value="">+ group</option>
          {options.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
