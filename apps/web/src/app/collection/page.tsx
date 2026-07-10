"use client";

import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { FormField } from "@/components/FormField";
import { RarityBadge } from "@/components/RarityBadge";
import {
  COLLECTION_STATUS_OPTIONS,
  type Card,
  type CollectionItem,
  type CollectionItemInput,
  type CollectionSummary,
  createCollectionItem,
  deleteCollectionItem,
  fetchCards,
  fetchCollectionItems,
  fetchCollectionSummary,
  updateCollectionItem,
} from "@/lib/api";
import { cardDisplayName, formatDate, formatJpy } from "@/lib/format";

const STATUS_OPTIONS: readonly string[] = COLLECTION_STATUS_OPTIONS;

const STATUS_FILTERS = [
  { value: "", label: "All" },
  ...STATUS_OPTIONS.map((s) => ({ value: s, label: s })),
];

interface FormState {
  card_id: string;
  quantity: string;
  condition_label: string;
  purchase_price_jpy: string;
  purchase_date: string;
  purchase_source: string;
  target_sell_price_jpy: string;
  status: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  card_id: "",
  quantity: "1",
  condition_label: "",
  purchase_price_jpy: "",
  purchase_date: "",
  purchase_source: "",
  target_sell_price_jpy: "",
  status: "hold",
  notes: "",
};

function itemToForm(item: CollectionItem): FormState {
  return {
    card_id: String(item.card_id),
    quantity: String(item.quantity),
    condition_label: item.condition_label ?? "",
    purchase_price_jpy:
      item.purchase_price_jpy === null ? "" : String(item.purchase_price_jpy),
    purchase_date: item.purchase_date ?? "",
    purchase_source: item.purchase_source ?? "",
    target_sell_price_jpy:
      item.target_sell_price_jpy === null
        ? ""
        : String(item.target_sell_price_jpy),
    status: item.status,
    notes: item.notes ?? "",
  };
}

export default function CollectionPage() {
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listStatus, setListStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );

  const [summary, setSummary] = useState<CollectionSummary | null>(null);

  const [allCards, setAllCards] = useState<Card[]>([]);
  const [cardSearch, setCardSearch] = useState("");

  const [statusFilter, setStatusFilter] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");
  const [cardCodeInput, setCardCodeInput] = useState("");

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);

  useEffect(() => {
    fetchCards()
      .then(setAllCards)
      .catch(() => setAllCards([]));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setCardCodeFilter(cardCodeInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [cardCodeInput]);

  function refreshSummary() {
    fetchCollectionSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
  }

  function refreshList() {
    fetchCollectionItems({
      status: statusFilter || undefined,
      card_code: cardCodeFilter || undefined,
      limit: 500,
    })
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
        setListStatus("ready");
      })
      .catch(() => setListStatus("error"));
  }

  useEffect(() => {
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, cardCodeFilter]);

  useEffect(() => {
    refreshSummary();
  }, []);

  const filteredCardOptions = useMemo(() => {
    const q = cardSearch.trim().toLowerCase();
    const sorted = [...allCards].sort((a, b) =>
      a.card_code.localeCompare(b.card_code),
    );
    if (!q) return sorted;
    return sorted.filter(
      (c) =>
        c.card_code.toLowerCase().includes(q) ||
        cardDisplayName(c).toLowerCase().includes(q),
    );
  }, [allCards, cardSearch]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function startEdit(item: CollectionItem) {
    setEditingId(item.id);
    setForm(itemToForm(item));
    setFormError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  }

  function validateForm(): CollectionItemInput | null {
    const cardId = Number(form.card_id);
    if (!form.card_id || Number.isNaN(cardId)) {
      setFormError("Select a card.");
      return null;
    }

    const quantity = form.quantity === "" ? 1 : Number(form.quantity);
    if (Number.isNaN(quantity) || quantity < 1) {
      setFormError("Quantity must be at least 1.");
      return null;
    }

    let purchasePrice: number | null = null;
    if (form.purchase_price_jpy !== "") {
      purchasePrice = Number(form.purchase_price_jpy);
      if (Number.isNaN(purchasePrice) || purchasePrice < 0) {
        setFormError("Purchase price must be 0 or greater.");
        return null;
      }
    }

    let targetSell: number | null = null;
    if (form.target_sell_price_jpy !== "") {
      targetSell = Number(form.target_sell_price_jpy);
      if (Number.isNaN(targetSell) || targetSell < 0) {
        setFormError("Target sell price must be 0 or greater.");
        return null;
      }
    }

    if (!STATUS_OPTIONS.includes(form.status)) {
      setFormError("Invalid status.");
      return null;
    }

    return {
      card_id: cardId,
      quantity,
      condition_label: form.condition_label || null,
      purchase_price_jpy: purchasePrice,
      purchase_date: form.purchase_date || null,
      purchase_source: form.purchase_source || null,
      target_sell_price_jpy: targetSell,
      notes: form.notes || null,
      status: form.status,
    };
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const body = validateForm();
    if (!body) return;

    setSaving(true);
    try {
      if (editingId !== null) {
        await updateCollectionItem(editingId, body);
      } else {
        await createCollectionItem(body);
      }
      setForm(EMPTY_FORM);
      setEditingId(null);
      refreshList();
      refreshSummary();
    } catch {
      setFormError(
        editingId !== null
          ? "Failed to update collection item."
          : "Failed to add collection item.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item: CollectionItem) {
    const confirmed = window.confirm(
      `Delete ${item.quantity}x ${item.card_code} — ${cardDisplayName(item)} from your collection? This cannot be undone.`,
    );
    if (!confirmed) return;

    setActionError(null);
    setPendingDeleteId(item.id);
    try {
      await deleteCollectionItem(item.id);
      if (editingId === item.id) cancelEdit();
      refreshList();
      refreshSummary();
    } catch {
      setActionError("Failed to delete collection item.");
    } finally {
      setPendingDeleteId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">
            Collection
          </h1>
          {listStatus === "ready" && (
            <span className="text-sm text-neutral-500">
              {total} item{total === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-6 space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="Total items" value={summary.total_items} />
              <StatCard
                label="Total quantity"
                value={summary.total_quantity}
              />
              <StatCard
                label="Total cost basis"
                value={formatJpy(summary.total_cost_basis_jpy)}
              />
              <StatCard
                label="With purchase price"
                value={summary.items_with_purchase_price}
              />
              <StatCard
                label="Missing purchase price"
                value={summary.items_missing_purchase_price}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
              <span className="text-xs uppercase tracking-wide text-neutral-500">
                By status
              </span>
              {STATUS_OPTIONS.map((s) => (
                <span
                  key={s}
                  className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1"
                >
                  <CollectionStatusBadge status={s} />
                  <span className="text-xs text-neutral-400">
                    {summary.items_by_status[s] ?? 0}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-200">
            {editingId !== null ? "Edit collection item" : "Add collection item"}
          </h2>

          {formError && (
            <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
              {formError}
            </div>
          )}

          <form onSubmit={submitForm} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Card">
                <input
                  type="text"
                  value={cardSearch}
                  onChange={(e) => setCardSearch(e.target.value)}
                  placeholder="Search card code or name…"
                  className="mb-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600"
                />
                <select
                  value={form.card_id}
                  onChange={(e) => updateField("card_id", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                >
                  <option value="">Select a card…</option>
                  {filteredCardOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.card_code} — {cardDisplayName(c)}
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Quantity">
                <input
                  type="number"
                  min={1}
                  value={form.quantity}
                  onChange={(e) => updateField("quantity", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Condition">
                <input
                  type="text"
                  value={form.condition_label}
                  onChange={(e) =>
                    updateField("condition_label", e.target.value)
                  }
                  placeholder="raw, PSA 10, …"
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                />
              </FormField>

              <FormField label="Purchase price (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.purchase_price_jpy}
                  onChange={(e) =>
                    updateField("purchase_price_jpy", e.target.value)
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Purchase date">
                <input
                  type="date"
                  value={form.purchase_date}
                  onChange={(e) => updateField("purchase_date", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Purchase source">
                <input
                  type="text"
                  value={form.purchase_source}
                  onChange={(e) =>
                    updateField("purchase_source", e.target.value)
                  }
                  placeholder="Yuyu-Tei, SNKRDUNK, …"
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                />
              </FormField>

              <FormField label="Target sell price (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.target_sell_price_jpy}
                  onChange={(e) =>
                    updateField("target_sell_price_jpy", e.target.value)
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Status">
                <select
                  value={form.status}
                  onChange={(e) => updateField("status", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Notes">
                <input
                  type="text"
                  value={form.notes}
                  onChange={(e) => updateField("notes", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
              >
                {saving
                  ? "Saving…"
                  : editingId !== null
                    ? "Update item"
                    : "Add item"}
              </button>
              {editingId !== null && (
                <button
                  type="button"
                  onClick={cancelEdit}
                  disabled={saving}
                  className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                >
                  Cancel
                </button>
              )}
            </div>
          </form>
        </section>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                  statusFilter === f.value
                    ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                    : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={cardCodeInput}
            onChange={(e) => setCardCodeInput(e.target.value)}
            placeholder="Filter by card code…"
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
          />
        </div>

        {actionError && (
          <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {actionError}
          </div>
        )}

        {listStatus === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading collection…
          </div>
        )}

        {listStatus === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load collection from the API. Is the backend running?
          </div>
        )}

        {listStatus === "ready" && items.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No collection items yet
          </div>
        )}

        {listStatus === "ready" && items.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Code</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Set</th>
                  <th className="px-3 py-2 font-medium">Rarity</th>
                  <th className="px-3 py-2 font-medium">Variant</th>
                  <th className="px-3 py-2 font-medium">Lang</th>
                  <th className="px-3 py-2 font-medium">Qty</th>
                  <th className="px-3 py-2 font-medium">Condition</th>
                  <th className="px-3 py-2 font-medium">Purchase price</th>
                  <th className="px-3 py-2 font-medium">Purchase date</th>
                  <th className="px-3 py-2 font-medium">Purchase source</th>
                  <th className="px-3 py-2 font-medium">Target sell</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Notes</th>
                  <th className="px-3 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                      {item.card_code}
                    </td>
                    <td className="px-3 py-2 font-medium text-neutral-100">
                      {cardDisplayName(item)}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {item.set_code}
                    </td>
                    <td className="px-3 py-2">
                      <RarityBadge rarity={item.rarity} />
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {item.variant ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {item.language}
                    </td>
                    <td className="px-3 py-2 text-neutral-200">
                      {item.quantity}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {item.condition_label ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-200">
                      {formatJpy(item.purchase_price_jpy)}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {formatDate(item.purchase_date)}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {item.purchase_source ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-200">
                      {formatJpy(item.target_sell_price_jpy)}
                    </td>
                    <td className="px-3 py-2">
                      <CollectionStatusBadge status={item.status} />
                    </td>
                    <td className="max-w-xs px-3 py-2">
                      {item.notes ? (
                        <span
                          className="block truncate text-neutral-400"
                          title={item.notes}
                        >
                          {item.notes}
                        </span>
                      ) : (
                        <span className="text-neutral-600">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-2">
                        <button
                          onClick={() => startEdit(item)}
                          className="text-xs font-medium text-sky-400 hover:text-sky-300"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(item)}
                          disabled={pendingDeleteId === item.id}
                          className="text-xs font-medium text-rose-400 hover:text-rose-300 disabled:opacity-50"
                        >
                          {pendingDeleteId === item.id
                            ? "Deleting…"
                            : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-neutral-100">
        {value}
      </div>
    </div>
  );
}
