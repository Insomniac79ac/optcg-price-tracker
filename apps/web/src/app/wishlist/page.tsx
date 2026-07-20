"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { FormField } from "@/components/FormField";
import { PaginationControls } from "@/components/PaginationControls";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState, MissingValue } from "@/components/StateBlocks";
import { WishlistImportExport } from "@/components/WishlistImportExport";
import { WishlistPriorityBadge } from "@/components/WishlistPriorityBadge";
import { WishlistStatusBadge } from "@/components/WishlistStatusBadge";
import {
  WISHLIST_PRIORITIES,
  WISHLIST_STATUSES,
  type Card,
  type CollectionItem,
  type WishlistItem,
  type WishlistItemInput,
  type WishlistPriority,
  type WishlistSummary,
  convertWishlistItemToCollection,
  createWishlistItem,
  fetchCards,
  fetchCollectionItems,
  fetchWishlistItems,
  fetchWishlistSummary,
  markWishlistItemPurchased,
  removeWishlistItem,
  updateWishlistItem,
} from "@/lib/api";
import { cardDisplayName, formatJpy, formatSignedJpy, formatSignedPct } from "@/lib/format";

const ALL_OPTION = { value: "", label: "All" };
const LIMIT_OPTIONS = [25, 50, 100, 200] as const;
const STATUS_FILTERS = [ALL_OPTION, ...WISHLIST_STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") }))];
const PRIORITY_FILTERS = [ALL_OPTION, ...WISHLIST_PRIORITIES.map((p) => ({ value: p, label: p }))];
const TARGET_HIT_OPTIONS = [
  ALL_OPTION,
  { value: "true", label: "Target hit" },
  { value: "false", label: "Not hit" },
];
const OWNED_OPTIONS = [
  ALL_OPTION,
  { value: "true", label: "Owned" },
  { value: "false", label: "Unowned" },
];

interface FormState {
  card_id: string;
  priority: WishlistPriority;
  target_buy_price_jpy: string;
  max_buy_price_jpy: string;
  preferred_condition: string;
  preferred_source: string;
  desired_quantity: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  card_id: "",
  priority: "medium",
  target_buy_price_jpy: "",
  max_buy_price_jpy: "",
  preferred_condition: "",
  preferred_source: "",
  desired_quantity: "1",
  notes: "",
};

function itemToForm(item: WishlistItem): FormState {
  return {
    card_id: String(item.card_id),
    priority: item.priority as WishlistPriority,
    target_buy_price_jpy: item.target_buy_price_jpy === null ? "" : String(item.target_buy_price_jpy),
    max_buy_price_jpy: item.max_buy_price_jpy === null ? "" : String(item.max_buy_price_jpy),
    preferred_condition: item.preferred_condition ?? "",
    preferred_source: item.preferred_source ?? "",
    desired_quantity: String(item.desired_quantity),
    notes: item.notes ?? "",
  };
}

export default function WishlistPage() {
  const [items, setItems] = useState<WishlistItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listStatus, setListStatus] = useState<"loading" | "error" | "ready">("loading");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [summary, setSummary] = useState<WishlistSummary | null>(null);

  const [allCards, setAllCards] = useState<Card[]>([]);
  const [cardSearch, setCardSearch] = useState("");

  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [targetHitFilter, setTargetHitFilter] = useState("");
  const [ownedFilter, setOwnedFilter] = useState("");
  const [setCodeFilter, setSetCodeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [cardCodeInput, setCardCodeInput] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);

  const [purchaseTargetId, setPurchaseTargetId] = useState<number | null>(null);
  const [convertTargetId, setConvertTargetId] = useState<number | null>(null);

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
    fetchWishlistSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
  }

  function refreshList() {
    fetchWishlistItems({
      status: statusFilter || undefined,
      priority: priorityFilter || undefined,
      target_hit: targetHitFilter === "" ? undefined : targetHitFilter === "true",
      owned: ownedFilter === "" ? undefined : ownedFilter === "true",
      set_code: setCodeFilter || undefined,
      rarity: rarityFilter || undefined,
      card_code: cardCodeFilter || undefined,
      limit,
      offset,
    })
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
        setListStatus("ready");
      })
      .catch(() => setListStatus("error"));
  }

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filter's result set is otherwise almost certainly out of range for
  // the new one.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, priorityFilter, targetHitFilter, ownedFilter, setCodeFilter, rarityFilter, cardCodeFilter, limit]);

  useEffect(() => {
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, priorityFilter, targetHitFilter, ownedFilter, setCodeFilter, rarityFilter, cardCodeFilter, limit, offset]);

  useEffect(() => {
    refreshSummary();
  }, []);

  const setCodeOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.set_code))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const rarityOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.rarity))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const filteredCardOptions = useMemo(() => {
    const q = cardSearch.trim().toLowerCase();
    const sorted = [...allCards].sort((a, b) => a.card_code.localeCompare(b.card_code));
    if (!q) return sorted;
    return sorted.filter(
      (c) =>
        c.card_code.toLowerCase().includes(q) || cardDisplayName(c).toLowerCase().includes(q),
    );
  }, [allCards, cardSearch]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function startEdit(item: WishlistItem) {
    setEditingId(item.id);
    setForm(itemToForm(item));
    setFormError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  }

  function validateForm(): WishlistItemInput | null {
    const cardId = Number(form.card_id);
    if (!form.card_id || Number.isNaN(cardId)) {
      setFormError("Select a card.");
      return null;
    }

    const desiredQuantity = form.desired_quantity === "" ? 1 : Number(form.desired_quantity);
    if (Number.isNaN(desiredQuantity) || desiredQuantity < 1) {
      setFormError("Desired quantity must be at least 1.");
      return null;
    }

    let targetBuy: number | null = null;
    if (form.target_buy_price_jpy !== "") {
      targetBuy = Number(form.target_buy_price_jpy);
      if (Number.isNaN(targetBuy) || targetBuy < 0) {
        setFormError("Target buy price must be 0 or greater.");
        return null;
      }
    }

    let maxBuy: number | null = null;
    if (form.max_buy_price_jpy !== "") {
      maxBuy = Number(form.max_buy_price_jpy);
      if (Number.isNaN(maxBuy) || maxBuy < 0) {
        setFormError("Max buy price must be 0 or greater.");
        return null;
      }
    }

    return {
      card_id: cardId,
      priority: form.priority,
      target_buy_price_jpy: targetBuy,
      max_buy_price_jpy: maxBuy,
      preferred_condition: form.preferred_condition || null,
      preferred_source: form.preferred_source || null,
      desired_quantity: desiredQuantity,
      notes: form.notes || null,
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
        const { card_id: _cardId, ...updateBody } = body;
        void _cardId;
        await updateWishlistItem(editingId, updateBody);
      } else {
        await createWishlistItem(body);
      }
      setForm(EMPTY_FORM);
      setEditingId(null);
      refreshList();
      refreshSummary();
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : editingId !== null
            ? "Failed to update wishlist item."
            : "Failed to add wishlist item.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(item: WishlistItem) {
    const confirmed = window.confirm(
      `Remove ${item.card_code} — ${cardDisplayName(item)} from your wishlist? This cannot be undone.`,
    );
    if (!confirmed) return;

    setActionError(null);
    setPendingActionId(item.id);
    try {
      await removeWishlistItem(item.id);
      if (editingId === item.id) cancelEdit();
      refreshList();
      refreshSummary();
    } catch {
      setActionError("Failed to remove wishlist item.");
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleMarkPassed(item: WishlistItem) {
    setActionError(null);
    setPendingActionId(item.id);
    try {
      await updateWishlistItem(item.id, { status: "passed" });
      refreshList();
      refreshSummary();
    } catch {
      setActionError("Failed to mark item as passed.");
    } finally {
      setPendingActionId(null);
    }
  }

  const purchaseTarget = items.find((i) => i.id === purchaseTargetId) ?? null;
  const convertTarget = items.find((i) => i.id === convertTargetId) ?? null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">Wishlist</h1>
            <Link href="/collection" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
              Collection →
            </Link>
            <Link href="/analytics/wishlist" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
              Analytics →
            </Link>
            <Link href="/market/opportunities" className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300">
              Opportunities →
            </Link>
          </div>
          {listStatus === "ready" && (
            <span className="text-sm text-neutral-500">
              {total} item{total === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-6 space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="Total wishlist items" value={summary.total_wishlist_items} />
              <StatCard label="Watching" value={summary.watching} />
              <StatCard label="Target hit" value={summary.items_with_target_hit} />
              <StatCard label="Purchased" value={summary.purchased} />
              <StatCard label="Grails" value={summary.grail_count} />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="High priority" value={summary.high_priority_count} />
              <StatCard label="Total target budget" value={formatJpy(summary.total_target_budget_jpy)} />
              <StatCard label="Total max budget" value={formatJpy(summary.total_max_budget_jpy)} />
              <StatCard label="Owned already" value={summary.items_owned_already} />
              <StatCard label="Passed" value={summary.passed} />
            </div>
          </div>
        )}

        <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-200">
            {editingId !== null ? "Edit wishlist item" : "Add to wishlist"}
          </h2>

          {formError && (
            <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
              {formError}
            </div>
          )}

          <form onSubmit={submitForm} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <FormField label="Card">
                <input
                  type="text"
                  value={cardSearch}
                  onChange={(e) => setCardSearch(e.target.value)}
                  placeholder="Search card code or name…"
                  disabled={editingId !== null}
                  className="mb-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 placeholder:text-neutral-600 disabled:opacity-50"
                />
                <select
                  value={form.card_id}
                  onChange={(e) => updateField("card_id", e.target.value)}
                  disabled={editingId !== null}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 disabled:opacity-50"
                >
                  <option value="">Select a card…</option>
                  {filteredCardOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.card_code} — {cardDisplayName(c)}
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Priority">
                <select
                  value={form.priority}
                  onChange={(e) => updateField("priority", e.target.value as WishlistPriority)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                >
                  {WISHLIST_PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Target buy price (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.target_buy_price_jpy}
                  onChange={(e) => updateField("target_buy_price_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Max buy price (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.max_buy_price_jpy}
                  onChange={(e) => updateField("max_buy_price_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Preferred condition">
                <input
                  type="text"
                  value={form.preferred_condition}
                  onChange={(e) => updateField("preferred_condition", e.target.value)}
                  placeholder="raw, PSA 10, …"
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                />
              </FormField>

              <FormField label="Preferred source">
                <input
                  type="text"
                  value={form.preferred_source}
                  onChange={(e) => updateField("preferred_source", e.target.value)}
                  placeholder="yuyutei, snkrdunk, local_shop, …"
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                />
              </FormField>

              <FormField label="Desired quantity">
                <input
                  type="number"
                  min={1}
                  value={form.desired_quantity}
                  onChange={(e) => updateField("desired_quantity", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
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
                {saving ? "Saving…" : editingId !== null ? "Update item" : "Add to wishlist"}
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

        <WishlistImportExport
          onImported={() => {
            refreshList();
            refreshSummary();
          }}
        />

        <div className="mb-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={STATUS_FILTERS} />
            <FilterSelect label="Priority" value={priorityFilter} onChange={setPriorityFilter} options={PRIORITY_FILTERS} />
            <FilterSelect label="Target hit" value={targetHitFilter} onChange={setTargetHitFilter} options={TARGET_HIT_OPTIONS} />
            <FilterSelect label="Owned" value={ownedFilter} onChange={setOwnedFilter} options={OWNED_OPTIONS} />
            <FilterSelect label="Set" value={setCodeFilter} onChange={setSetCodeFilter} options={setCodeOptions} />
            <FilterSelect label="Rarity" value={rarityFilter} onChange={setRarityFilter} options={rarityOptions} />
            <input
              type="text"
              value={cardCodeInput}
              onChange={(e) => setCardCodeInput(e.target.value)}
              placeholder="Filter by card code…"
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
          </div>
        </div>

        {actionError && (
          <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {actionError}
          </div>
        )}

        {listStatus === "loading" && <LoadingState>Loading wishlist…</LoadingState>}

        {listStatus === "error" && (
          <ErrorState>Failed to load wishlist from the API.</ErrorState>
        )}

        {listStatus === "ready" && items.length === 0 && (
          <EmptyState>No wishlist items yet</EmptyState>
        )}

        {listStatus === "ready" && items.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Priority</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Set</th>
                  <th className="px-2 py-1.5 font-medium">Rarity</th>
                  <th className="px-2 py-1.5 font-medium">Desired</th>
                  <th className="px-2 py-1.5 font-medium">Owned</th>
                  <th className="px-2 py-1.5 font-medium">Target buy</th>
                  <th className="px-2 py-1.5 font-medium">Max buy</th>
                  <th className="px-2 py-1.5 font-medium">Current price</th>
                  <th className="px-2 py-1.5 font-medium">Price source</th>
                  <th className="px-2 py-1.5 font-medium">Gap to target</th>
                  <th className="px-2 py-1.5 font-medium">Target hit</th>
                  <th className="px-2 py-1.5 font-medium">Condition</th>
                  <th className="px-2 py-1.5 font-medium">Source</th>
                  <th className="px-2 py-1.5 font-medium">Notes</th>
                  <th className="px-2 py-1.5 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
                    <td className="px-2 py-1.5">
                      <WishlistPriorityBadge priority={item.priority} />
                    </td>
                    <td className="px-2 py-1.5">
                      <WishlistStatusBadge status={item.status} />
                    </td>
                    <td className="px-2 py-1.5 font-mono text-neutral-400">
                      <Link href={`/cards/${item.card_id}`} className="hover:text-sky-400">
                        {item.card_code}
                      </Link>
                    </td>
                    <td className="px-2 py-1.5 font-medium text-neutral-100">{cardDisplayName(item)}</td>
                    <td className="px-2 py-1.5 text-neutral-400">{item.set_code}</td>
                    <td className="px-2 py-1.5">
                      <RarityBadge rarity={item.rarity} />
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">{item.desired_quantity}</td>
                    <td className="px-2 py-1.5 text-neutral-200">{item.owned_quantity}</td>
                    <td className="px-2 py-1.5 text-neutral-200">{formatJpy(item.target_buy_price_jpy)}</td>
                    <td className="px-2 py-1.5 text-neutral-200">{formatJpy(item.max_buy_price_jpy)}</td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {item.preferred_current_price_jpy === null ? (
                        <MissingValue label="no price data" italic />
                      ) : (
                        formatJpy(item.preferred_current_price_jpy)
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {item.preferred_current_price_source === "snkrdunk_floor"
                        ? "SNKRDUNK floor"
                        : item.preferred_current_price_source === "yuyutei_sell"
                          ? "Yuyu-Tei sell"
                          : "—"}
                    </td>
                    <td className="px-2 py-1.5">
                      {item.gap_to_target_jpy === null ? (
                        <MissingValue />
                      ) : (
                        <span className={item.gap_to_target_jpy <= 0 ? "text-emerald-400" : "text-neutral-300"}>
                          {formatSignedJpy(item.gap_to_target_jpy)}{" "}
                          <span className="text-neutral-500">({formatSignedPct(item.gap_to_target_pct)})</span>
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {item.target_hit ? (
                        <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-500/30">
                          hit
                        </span>
                      ) : (
                        <MissingValue />
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">{item.preferred_condition ?? "—"}</td>
                    <td className="px-2 py-1.5 text-neutral-400">{item.preferred_source ?? "—"}</td>
                    <td className="max-w-[10rem] px-2 py-1.5 text-neutral-400">{item.notes ?? "—"}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => startEdit(item)}
                          className="text-xs font-medium text-sky-400 hover:text-sky-300"
                        >
                          Edit
                        </button>
                        {item.status !== "removed" && (
                          <button
                            onClick={() => handleRemove(item)}
                            disabled={pendingActionId === item.id}
                            className="text-xs font-medium text-rose-400 hover:text-rose-300 disabled:opacity-50"
                          >
                            Remove
                          </button>
                        )}
                        {item.status !== "passed" && item.status !== "purchased" && item.status !== "removed" && (
                          <button
                            onClick={() => handleMarkPassed(item)}
                            disabled={pendingActionId === item.id}
                            className="text-xs font-medium text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
                          >
                            Mark passed
                          </button>
                        )}
                        {item.status !== "purchased" && (
                          <>
                            <button
                              onClick={() => setPurchaseTargetId(item.id)}
                              className="text-xs font-medium text-violet-400 hover:text-violet-300"
                            >
                              Mark purchased
                            </button>
                            <button
                              onClick={() => setConvertTargetId(item.id)}
                              className="text-xs font-medium text-emerald-400 hover:text-emerald-300"
                            >
                              Convert to collection
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {listStatus === "ready" && (
          <div className="mt-3">
            <PaginationControls
              offset={offset}
              limit={limit}
              total={total}
              onOffsetChange={setOffset}
              limitOptions={LIMIT_OPTIONS}
              onLimitChange={setLimit}
            />
          </div>
        )}
      </main>

      {purchaseTarget && (
        <MarkPurchasedModal
          item={purchaseTarget}
          onClose={() => setPurchaseTargetId(null)}
          onDone={() => {
            setPurchaseTargetId(null);
            refreshList();
            refreshSummary();
          }}
        />
      )}

      {convertTarget && (
        <ConvertToCollectionModal
          item={convertTarget}
          onClose={() => setConvertTargetId(null)}
          onDone={() => {
            setConvertTargetId(null);
            refreshList();
            refreshSummary();
          }}
        />
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 truncate text-2xl font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-neutral-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-lg border border-neutral-800 bg-neutral-900 p-4 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-neutral-100">{title}</h3>
          <button onClick={onClose} className="text-xs text-neutral-500 hover:text-neutral-200">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function MarkPurchasedModal({
  item,
  onClose,
  onDone,
}: {
  item: WishlistItem;
  onClose: () => void;
  onDone: () => void;
}) {
  const [candidates, setCandidates] = useState<CollectionItem[]>([]);
  const [collectionItemId, setCollectionItemId] = useState("");
  const [acquiredQuantity, setAcquiredQuantity] = useState("1");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCollectionItems({ card_id: item.card_id })
      .then((data) => setCandidates(data.items))
      .catch(() => setCandidates([]));
  }, [item.card_id]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const id = Number(collectionItemId);
    if (!collectionItemId || Number.isNaN(id)) {
      setError("Select the collection item you already added.");
      return;
    }
    const qty = Number(acquiredQuantity);
    if (Number.isNaN(qty) || qty < 1) {
      setError("Acquired quantity must be at least 1.");
      return;
    }
    setSaving(true);
    try {
      await markWishlistItemPurchased(item.id, { collection_item_id: id, acquired_quantity: qty });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark as purchased.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Mark purchased — ${item.card_code}`} onClose={onClose}>
      <p className="mb-3 text-xs text-neutral-500">
        Links this wishlist item to a collection item you already added. This does not create a
        new collection item — use &quot;Convert to collection&quot; for that.
      </p>
      {error && (
        <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}
      <form onSubmit={submit} className="space-y-3">
        <FormField label="Collection item">
          <select
            value={collectionItemId}
            onChange={(e) => setCollectionItemId(e.target.value)}
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
          >
            <option value="">Select…</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.id} · {c.quantity}× {c.condition_label ?? "raw"} · {formatJpy(c.purchase_price_jpy)}
              </option>
            ))}
          </select>
          {candidates.length === 0 && (
            <p className="mt-1 text-[11px] text-neutral-600">
              No existing collection items found for this card yet.
            </p>
          )}
        </FormField>
        <FormField label="Acquired quantity">
          <input
            type="number"
            min={1}
            value={acquiredQuantity}
            onChange={(e) => setAcquiredQuantity(e.target.value)}
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
          />
        </FormField>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
          >
            {saving ? "Saving…" : "Mark purchased"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100"
          >
            Cancel
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function ConvertToCollectionModal({
  item,
  onClose,
  onDone,
}: {
  item: WishlistItem;
  onClose: () => void;
  onDone: () => void;
}) {
  const [quantity, setQuantity] = useState(String(item.desired_quantity || 1));
  const [conditionLabel, setConditionLabel] = useState(item.preferred_condition ?? "");
  const [purchasePrice, setPurchasePrice] = useState(
    item.preferred_current_price_jpy !== null ? String(item.preferred_current_price_jpy) : "",
  );
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseSource, setPurchaseSource] = useState(item.preferred_source ?? "");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const qty = Number(quantity);
    if (Number.isNaN(qty) || qty < 1) {
      setError("Quantity must be at least 1.");
      return;
    }
    let price: number | null = null;
    if (purchasePrice !== "") {
      price = Number(purchasePrice);
      if (Number.isNaN(price) || price < 0) {
        setError("Purchase price must be 0 or greater.");
        return;
      }
    }

    setSaving(true);
    try {
      await convertWishlistItemToCollection(item.id, {
        quantity: qty,
        condition_label: conditionLabel || null,
        purchase_price_jpy: price,
        purchase_date: purchaseDate || null,
        purchase_source: purchaseSource || null,
        status: "hold",
        notes: notes || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to convert to collection item.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Convert to collection — ${item.card_code}`} onClose={onClose}>
      {error && (
        <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Quantity">
            <input
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </FormField>
          <FormField label="Condition">
            <input
              type="text"
              value={conditionLabel}
              onChange={(e) => setConditionLabel(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </FormField>
          <FormField label="Purchase price (JPY)">
            <input
              type="number"
              min={0}
              value={purchasePrice}
              onChange={(e) => setPurchasePrice(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </FormField>
          <FormField label="Purchase date">
            <input
              type="date"
              value={purchaseDate}
              onChange={(e) => setPurchaseDate(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </FormField>
          <FormField label="Purchase source">
            <input
              type="text"
              value={purchaseSource}
              onChange={(e) => setPurchaseSource(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </FormField>
          <FormField label="Notes">
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
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
            {saving ? "Saving…" : "Convert to collection"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100"
          >
            Cancel
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
