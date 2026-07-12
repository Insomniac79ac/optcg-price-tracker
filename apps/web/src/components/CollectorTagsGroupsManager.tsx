"use client";

import { useState } from "react";

import {
  type CollectorGroup,
  type CollectorTag,
  createCollectorGroup,
  createCollectorTag,
  deleteCollectorGroup,
  deleteCollectorTag,
  updateCollectorGroup,
  updateCollectorTag,
} from "@/lib/api";

import { CollectorGroupLabel } from "./CollectorGroupLabel";
import { CollectorTagBadge } from "./CollectorTagBadge";
import { FormField } from "./FormField";

export function CollectorTagsGroupsManager({
  tags,
  groups,
  onChanged,
}: {
  tags: CollectorTag[];
  groups: CollectorGroup[];
  onChanged: () => void;
}) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">Tags &amp; groups</h2>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <TagManager tags={tags} onChanged={onChanged} />
        <GroupManager groups={groups} onChanged={onChanged} />
      </div>
    </section>
  );
}

function TagManager({
  tags,
  onChanged,
}: {
  tags: CollectorTag[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");
  const [editDescription, setEditDescription] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await createCollectorTag({
        name,
        color: color || null,
        description: description || null,
      });
      setName("");
      setColor("");
      setDescription("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create tag.");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(tag: CollectorTag) {
    setEditingId(tag.id);
    setEditName(tag.name);
    setEditColor(tag.color ?? "");
    setEditDescription(tag.description ?? "");
    setError(null);
  }

  async function handleSaveEdit(tagId: number) {
    setError(null);
    setSaving(true);
    try {
      await updateCollectorTag(tagId, {
        name: editName,
        color: editColor || null,
        description: editDescription || null,
      });
      setEditingId(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update tag.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(tag: CollectorTag) {
    const confirmed = window.confirm(
      `Delete tag "${tag.name}"? This removes it from every card and collection item it's assigned to.`,
    );
    if (!confirmed) return;
    setError(null);
    try {
      await deleteCollectorTag(tag.id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete tag.");
    }
  }

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        Tags
      </h3>

      {error && (
        <div className="mb-2 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      <form onSubmit={handleCreate} className="mb-3 flex flex-wrap items-end gap-2">
        <FormField label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Grade candidates"
            className="w-36 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600"
          />
        </FormField>
        <FormField label="Color">
          <input
            type="text"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            placeholder="#888888"
            className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600"
          />
        </FormField>
        <FormField label="Description">
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-40 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100"
          />
        </FormField>
        <button
          type="submit"
          disabled={saving || !name.trim()}
          className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          Create tag
        </button>
      </form>

      {tags.length === 0 ? (
        <p className="text-xs text-neutral-600">No tags yet.</p>
      ) : (
        <div className="space-y-1.5">
          {tags.map((tag) =>
            editingId === tag.id ? (
              <div
                key={tag.id}
                className="flex flex-wrap items-center gap-2 rounded border border-neutral-800 bg-neutral-950 p-2"
              >
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100"
                />
                <input
                  type="text"
                  value={editColor}
                  onChange={(e) => setEditColor(e.target.value)}
                  placeholder="#888888"
                  className="w-20 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600"
                />
                <input
                  type="text"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-32 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100"
                />
                <button
                  type="button"
                  onClick={() => handleSaveEdit(tag.id)}
                  disabled={saving || !editName.trim()}
                  className="rounded bg-neutral-100 px-2 py-1 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditingId(null)}
                  className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:text-neutral-100"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div
                key={tag.id}
                className="flex flex-wrap items-center gap-2 rounded border border-neutral-800 px-2 py-1.5"
              >
                <CollectorTagBadge tag={tag} />
                {tag.description && (
                  <span className="text-xs text-neutral-500">{tag.description}</span>
                )}
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={() => startEdit(tag)}
                    className="text-xs font-medium text-sky-400 hover:text-sky-300"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(tag)}
                    className="text-xs font-medium text-rose-400 hover:text-rose-300"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}

function GroupManager({
  groups,
  onChanged,
}: {
  groups: CollectorGroup[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sortOrder, setSortOrder] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editSortOrder, setEditSortOrder] = useState("0");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await createCollectorGroup({
        name,
        description: description || null,
        sort_order: sortOrder === "" ? 0 : Number(sortOrder),
      });
      setName("");
      setDescription("");
      setSortOrder("0");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create group.");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(group: CollectorGroup) {
    setEditingId(group.id);
    setEditName(group.name);
    setEditDescription(group.description ?? "");
    setEditSortOrder(String(group.sort_order));
    setError(null);
  }

  async function handleSaveEdit(groupId: number) {
    setError(null);
    setSaving(true);
    try {
      await updateCollectorGroup(groupId, {
        name: editName,
        description: editDescription || null,
        sort_order: editSortOrder === "" ? 0 : Number(editSortOrder),
      });
      setEditingId(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update group.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(group: CollectorGroup) {
    const confirmed = window.confirm(
      `Delete group "${group.name}"? This removes it from every collection item it's assigned to.`,
    );
    if (!confirmed) return;
    setError(null);
    try {
      await deleteCollectorGroup(group.id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete group.");
    }
  }

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        Groups
      </h3>

      {error && (
        <div className="mb-2 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      <form onSubmit={handleCreate} className="mb-3 flex flex-wrap items-end gap-2">
        <FormField label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Manga wants"
            className="w-36 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600"
          />
        </FormField>
        <FormField label="Description">
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-40 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100"
          />
        </FormField>
        <FormField label="Sort">
          <input
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
            className="w-16 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100"
          />
        </FormField>
        <button
          type="submit"
          disabled={saving || !name.trim()}
          className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          Create group
        </button>
      </form>

      {groups.length === 0 ? (
        <p className="text-xs text-neutral-600">No groups yet.</p>
      ) : (
        <div className="space-y-1.5">
          {groups.map((group) =>
            editingId === group.id ? (
              <div
                key={group.id}
                className="flex flex-wrap items-center gap-2 rounded border border-neutral-800 bg-neutral-950 p-2"
              >
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100"
                />
                <input
                  type="text"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-32 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100"
                />
                <input
                  type="number"
                  value={editSortOrder}
                  onChange={(e) => setEditSortOrder(e.target.value)}
                  className="w-16 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-100"
                />
                <button
                  type="button"
                  onClick={() => handleSaveEdit(group.id)}
                  disabled={saving || !editName.trim()}
                  className="rounded bg-neutral-100 px-2 py-1 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditingId(null)}
                  className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:text-neutral-100"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div
                key={group.id}
                className="flex flex-wrap items-center gap-2 rounded border border-neutral-800 px-2 py-1.5"
              >
                <CollectorGroupLabel group={group} />
                <span className="text-[10px] text-neutral-600">sort {group.sort_order}</span>
                {group.description && (
                  <span className="text-xs text-neutral-500">{group.description}</span>
                )}
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={() => startEdit(group)}
                    className="text-xs font-medium text-sky-400 hover:text-sky-300"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(group)}
                    className="text-xs font-medium text-rose-400 hover:text-rose-300"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}
