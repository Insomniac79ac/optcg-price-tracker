"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionImportExport } from "@/components/CollectionImportExport";
import { CollectionItemGroupsCell } from "@/components/CollectionItemGroupsCell";
import { CollectionItemTagsCell } from "@/components/CollectionItemTagsCell";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { CollectionValuationSummary } from "@/components/CollectionValuationSummary";
import { CollectorTagsGroupsManager } from "@/components/CollectorTagsGroupsManager";
import { FormField } from "@/components/FormField";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import type { HistoryTimeframe } from "@/components/PortfolioValuationHistoryChart";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  COLLECTION_STATUS_OPTIONS,
  type Card,
  type CollectionItem,
  type CollectionItemInput,
  type CollectionSummary,
  type CollectorGroup,
  type CollectorTag,
  type GradedAdjustedValuation,
  type PortfolioValuation,
  type PortfolioValuationItem,
  type PortfolioValuationSnapshot,
  type SnkrdunkFloorSnapshot,
  type ValuationMode,
  type YuyuteiPriceSnapshot,
  assignCollectionItemGroup,
  assignCollectionItemTag,
  createCollectionItem,
  deleteCollectionItem,
  fetchCards,
  fetchCollectionItems,
  fetchCollectionSummary,
  fetchCollectionValuation,
  fetchCollectionValuationHistory,
  fetchCollectorGroups,
  fetchCollectorTags,
  unassignCollectionItemGroup,
  unassignCollectionItemTag,
  updateCollectionItem,
} from "@/lib/api";
import {
  cardDisplayName,
  formatJpy,
  formatSignedJpy,
  formatSignedPct,
} from "@/lib/format";

// Dynamically imported (recharts is a sizeable chunk) so pages that never
// render this chart don't pay for it. ssr: false sidesteps recharts'
// well-known SSR/hydration mismatch (it measures its container via
// ResizeObserver, which needs a real browser).
const PortfolioValuationHistoryChart = dynamic(
  () =>
    import("@/components/PortfolioValuationHistoryChart").then(
      (mod) => mod.PortfolioValuationHistoryChart,
    ),
  { ssr: false, loading: () => <LoadingState>Loading chart…</LoadingState> },
);

const STATUS_OPTIONS: readonly string[] = COLLECTION_STATUS_OPTIONS;

const STATUS_FILTERS = [
  { value: "", label: "All" },
  ...STATUS_OPTIONS.map((s) => ({ value: s, label: s })),
];

const ALL_OPTION = { value: "", label: "All" };

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

  const [valuation, setValuation] = useState<PortfolioValuation | null>(null);
  const [valuationStatus, setValuationStatus] = useState<
    "loading" | "error" | "ready"
  >("loading");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");

  const [historyTimeframe, setHistoryTimeframe] =
    useState<HistoryTimeframe>("30");
  const [history, setHistory] = useState<PortfolioValuationSnapshot[]>([]);
  const [historyStatus, setHistoryStatus] = useState<
    "loading" | "error" | "ready"
  >("loading");

  const [allCards, setAllCards] = useState<Card[]>([]);
  const [cardSearch, setCardSearch] = useState("");

  const [statusFilter, setStatusFilter] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");
  const [cardCodeInput, setCardCodeInput] = useState("");

  const [conditionFilter, setConditionFilter] = useState("");
  const [setCodeFilter, setSetCodeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [missingPricesOnly, setMissingPricesOnly] = useState(false);
  const [missingCostBasisOnly, setMissingCostBasisOnly] = useState(false);
  const [aboveTargetOnly, setAboveTargetOnly] = useState(false);

  const [allTags, setAllTags] = useState<CollectorTag[]>([]);
  const [allGroups, setAllGroups] = useState<CollectorGroup[]>([]);

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

  function refreshTagsAndGroups() {
    fetchCollectorTags()
      .then(setAllTags)
      .catch(() => setAllTags([]));
    fetchCollectorGroups()
      .then(setAllGroups)
      .catch(() => setAllGroups([]));
  }

  useEffect(() => {
    refreshTagsAndGroups();
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

  function refreshValuation(mode: ValuationMode = valuationMode) {
    fetchCollectionValuation(mode)
      .then((data) => {
        setValuation(data);
        setValuationStatus("ready");
      })
      .catch(() => setValuationStatus("error"));
  }

  function handleValuationModeChange(mode: ValuationMode) {
    setValuationMode(mode);
    refreshValuation(mode);
  }

  function refreshHistory(days: HistoryTimeframe) {
    setHistoryStatus("loading");
    fetchCollectionValuationHistory(days)
      .then((data) => {
        setHistory(data);
        setHistoryStatus("ready");
      })
      .catch(() => setHistoryStatus("error"));
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
    refreshValuation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refreshHistory(historyTimeframe);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyTimeframe]);

  const valuationByItemId = useMemo(() => {
    const map = new Map<number, PortfolioValuationItem>();
    for (const v of valuation?.items ?? []) {
      map.set(v.collection_item_id, v);
    }
    return map;
  }, [valuation]);

  const conditionOptions = useMemo(() => {
    const values = Array.from(
      new Set(items.map((i) => i.condition_label).filter((v): v is string => !!v)),
    ).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const setCodeOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.set_code))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const rarityOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.rarity))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const tagOptions = useMemo(
    () => [ALL_OPTION, ...allTags.map((t) => ({ value: String(t.id), label: t.name }))],
    [allTags],
  );

  const groupOptions = useMemo(
    () => [ALL_OPTION, ...allGroups.map((g) => ({ value: String(g.id), label: g.name }))],
    [allGroups],
  );

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (conditionFilter && (item.condition_label ?? "") !== conditionFilter) {
        return false;
      }
      if (setCodeFilter && item.set_code !== setCodeFilter) return false;
      if (rarityFilter && item.rarity !== rarityFilter) return false;
      if (tagFilter && !item.tags.some((t) => String(t.id) === tagFilter)) return false;
      if (groupFilter && !item.groups.some((g) => String(g.id) === groupFilter)) return false;

      const v = valuationByItemId.get(item.id);

      if (missingPricesOnly) {
        const missingAny = v
          ? v.flags.missing_yuyutei_sell ||
            v.flags.missing_yuyutei_buy ||
            v.flags.missing_snkrdunk_floor
          : true;
        if (!missingAny) return false;
      }

      if (missingCostBasisOnly) {
        const missingCostBasis = v
          ? v.flags.missing_cost_basis
          : item.purchase_price_jpy === null;
        if (!missingCostBasis) return false;
      }

      if (aboveTargetOnly) {
        const above = v ? v.flags.above_target_sell : false;
        if (!above) return false;
      }

      return true;
    });
  }, [
    items,
    conditionFilter,
    setCodeFilter,
    rarityFilter,
    tagFilter,
    groupFilter,
    missingPricesOnly,
    missingCostBasisOnly,
    aboveTargetOnly,
    valuationByItemId,
  ]);

  const cardsMissingPrices = useMemo(() => {
    if (!valuation) return 0;
    return valuation.items.filter(
      (v) =>
        v.flags.missing_yuyutei_sell ||
        v.flags.missing_yuyutei_buy ||
        v.flags.missing_snkrdunk_floor,
    ).length;
  }, [valuation]);

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
      refreshValuation();
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
      refreshValuation();
    } catch {
      setActionError("Failed to delete collection item.");
    } finally {
      setPendingDeleteId(null);
    }
  }

  async function handleAssignTag(itemId: number, tagId: number) {
    try {
      await assignCollectionItemTag(itemId, tagId);
      refreshList();
      refreshValuation();
    } catch {
      setActionError("Failed to assign tag.");
    }
  }

  async function handleUnassignTag(itemId: number, tagId: number) {
    try {
      await unassignCollectionItemTag(itemId, tagId);
      refreshList();
      refreshValuation();
    } catch {
      setActionError("Failed to remove tag.");
    }
  }

  async function handleAssignGroup(itemId: number, groupId: number) {
    try {
      await assignCollectionItemGroup(itemId, groupId);
      refreshList();
      refreshValuation();
    } catch {
      setActionError("Failed to assign group.");
    }
  }

  async function handleUnassignGroup(itemId: number, groupId: number) {
    try {
      await unassignCollectionItemGroup(itemId, groupId);
      refreshList();
      refreshValuation();
    } catch {
      setActionError("Failed to remove group.");
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Collection
            </h1>
            <Link
              href="/grading"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Grading →
            </Link>
            <Link
              href="/wishlist"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Wishlist →
            </Link>
          </div>
          {listStatus === "ready" && (
            <span className="text-sm text-neutral-500">
              {total} item{total === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <CollectionImportExport
          onImported={() => {
            refreshList();
            refreshSummary();
            refreshValuation();
          }}
        />

        <div className="mb-6">
          <CollectorTagsGroupsManager
            tags={allTags}
            groups={allGroups}
            onChanged={refreshTagsAndGroups}
          />
        </div>

        <CollectionValuationSummary
          valuation={valuation}
          valuationStatus={valuationStatus}
          valuationMode={valuationMode}
          onValuationModeChange={handleValuationModeChange}
          cardsMissingPrices={cardsMissingPrices}
        />

        <PortfolioValuationHistoryChart
          snapshots={history}
          status={historyStatus}
          timeframe={historyTimeframe}
          onTimeframeChange={setHistoryTimeframe}
        />

        {summary && (
          <div className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
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

        <div className="mb-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
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

          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect
              label="Condition"
              value={conditionFilter}
              onChange={setConditionFilter}
              options={conditionOptions}
            />
            <FilterSelect
              label="Set"
              value={setCodeFilter}
              onChange={setSetCodeFilter}
              options={setCodeOptions}
            />
            <FilterSelect
              label="Rarity"
              value={rarityFilter}
              onChange={setRarityFilter}
              options={rarityOptions}
            />
            <FilterSelect
              label="Tag"
              value={tagFilter}
              onChange={setTagFilter}
              options={tagOptions}
            />
            <FilterSelect
              label="Group"
              value={groupFilter}
              onChange={setGroupFilter}
              options={groupOptions}
            />
            <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-400">
              <input
                type="checkbox"
                checked={missingPricesOnly}
                onChange={(e) => setMissingPricesOnly(e.target.checked)}
                className="rounded border-neutral-700 bg-neutral-950"
              />
              Missing prices
            </label>
            <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-400">
              <input
                type="checkbox"
                checked={missingCostBasisOnly}
                onChange={(e) => setMissingCostBasisOnly(e.target.checked)}
                className="rounded border-neutral-700 bg-neutral-950"
              />
              Missing cost basis
            </label>
            <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-400">
              <input
                type="checkbox"
                checked={aboveTargetOnly}
                onChange={(e) => setAboveTargetOnly(e.target.checked)}
                className="rounded border-neutral-700 bg-neutral-950"
              />
              Above target sell
            </label>
            {items.length > 0 && (
              <span className="text-xs text-neutral-600">
                {filteredItems.length} of {items.length} shown
              </span>
            )}
          </div>
        </div>

        {actionError && (
          <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {actionError}
          </div>
        )}

        {listStatus === "loading" && <LoadingState>Loading collection…</LoadingState>}

        {listStatus === "error" && (
          <ErrorState>Failed to load collection from the API. Is the backend running?</ErrorState>
        )}

        {listStatus === "ready" && items.length === 0 && (
          <EmptyState>No collection items yet</EmptyState>
        )}

        {listStatus === "ready" && items.length > 0 && filteredItems.length === 0 && (
          <EmptyState>No items match the selected filters.</EmptyState>
        )}

        {listStatus === "ready" && filteredItems.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Set</th>
                  <th className="px-2 py-1.5 font-medium">Rarity</th>
                  <th className="px-2 py-1.5 font-medium">Variant</th>
                  <th className="px-2 py-1.5 font-medium">Qty</th>
                  <th className="px-2 py-1.5 font-medium">Condition</th>
                  <th className="px-2 py-1.5 font-medium">Purchase price</th>
                  <th className="px-2 py-1.5 font-medium">Cost basis</th>
                  <th className="px-2 py-1.5 font-medium">Yuyu-Tei sell</th>
                  <th className="px-2 py-1.5 font-medium">Yuyu-Tei buy</th>
                  <th className="px-2 py-1.5 font-medium">SNKRDUNK floor</th>
                  <th className="px-2 py-1.5 font-medium">P/L vs retail</th>
                  <th className="px-2 py-1.5 font-medium">P/L vs liquidation</th>
                  <th className="px-2 py-1.5 font-medium">P/L vs floor</th>
                  <th className="px-2 py-1.5 font-medium">Target sell</th>
                  <th className="px-2 py-1.5 font-medium">Flags</th>
                  {valuationMode === "graded_adjusted" && (
                    <>
                      <th className="px-2 py-1.5 font-medium">Graded-adj. value</th>
                      <th className="px-2 py-1.5 font-medium">Graded-adj. basis</th>
                      <th className="px-2 py-1.5 font-medium">Final grade</th>
                      <th className="px-2 py-1.5 font-medium">Grading company</th>
                      <th className="px-2 py-1.5 font-medium">P/L vs graded-adj.</th>
                    </>
                  )}
                  <th className="px-2 py-1.5 font-medium">Tags</th>
                  <th className="px-2 py-1.5 font-medium">Groups</th>
                  <th className="px-2 py-1.5 font-medium">Grading</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => {
                  const v = valuationByItemId.get(item.id);
                  return (
                    <tr
                      key={item.id}
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-2 py-1.5 font-mono text-neutral-400">
                        {item.card_code}
                      </td>
                      <td className="px-2 py-1.5 font-medium text-neutral-100">
                        {cardDisplayName(item)}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-400">
                        {item.set_code}
                      </td>
                      <td className="px-2 py-1.5">
                        <RarityBadge rarity={item.rarity} />
                      </td>
                      <td className="px-2 py-1.5 text-neutral-400">
                        {item.variant ?? "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-200">
                        {item.quantity}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-400">
                        {item.condition_label ?? "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-200">
                        {formatJpy(item.purchase_price_jpy)}
                      </td>
                      <td className="px-2 py-1.5">
                        <CostBasisCell costBasisJpy={v?.cost_basis_jpy ?? null} />
                      </td>
                      <td className="px-2 py-1.5">
                        <PriceSnapshotCell
                          snapshot={v?.latest_prices.yuyutei_sell ?? null}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <PriceSnapshotCell
                          snapshot={v?.latest_prices.yuyutei_buy ?? null}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <PriceSnapshotCell
                          snapshot={v?.latest_prices.snkrdunk_floor ?? null}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <PnlCell
                          pnlJpy={v?.valuations.pnl_vs_retail_jpy ?? null}
                          pnlPct={v?.valuations.pnl_vs_retail_pct ?? null}
                          missingPrice={v?.flags.missing_yuyutei_sell ?? true}
                          missingCostBasis={v?.flags.missing_cost_basis ?? true}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <PnlCell
                          pnlJpy={v?.valuations.pnl_vs_liquidation_jpy ?? null}
                          pnlPct={v?.valuations.pnl_vs_liquidation_pct ?? null}
                          missingPrice={v?.flags.missing_yuyutei_buy ?? true}
                          missingCostBasis={v?.flags.missing_cost_basis ?? true}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <PnlCell
                          pnlJpy={v?.valuations.pnl_vs_market_floor_jpy ?? null}
                          pnlPct={v?.valuations.pnl_vs_market_floor_pct ?? null}
                          missingPrice={v?.flags.missing_snkrdunk_floor ?? true}
                          missingCostBasis={v?.flags.missing_cost_basis ?? true}
                        />
                      </td>
                      <td className="px-2 py-1.5 text-neutral-200">
                        {formatJpy(item.target_sell_price_jpy)}
                      </td>
                      <td className="px-2 py-1.5">
                        {v ? (
                          <FlagsCell flags={v.flags} />
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      {valuationMode === "graded_adjusted" && (
                        <GradedAdjustedCells
                          gradedAdjusted={v?.graded_adjusted ?? null}
                          latestGradingStatus={item.latest_grading_status}
                        />
                      )}
                      <td className="px-2 py-1.5">
                        <CollectionItemTagsCell
                          assigned={item.tags}
                          available={allTags}
                          onAssign={(tagId) => handleAssignTag(item.id, tagId)}
                          onUnassign={(tagId) => handleUnassignTag(item.id, tagId)}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <CollectionItemGroupsCell
                          assigned={item.groups}
                          available={allGroups}
                          onAssign={(groupId) => handleAssignGroup(item.id, groupId)}
                          onUnassign={(groupId) => handleUnassignGroup(item.id, groupId)}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        {item.latest_grading_status ? (
                          <GradingStatusBadge status={item.latest_grading_status} />
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        <CollectionStatusBadge status={item.status} />
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex flex-wrap gap-2">
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
                          <Link
                            href={`/grading?item_id=${item.id}`}
                            className="text-xs font-medium text-violet-400 hover:text-violet-300"
                          >
                            Send to grading
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
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

function CostBasisCell({ costBasisJpy }: { costBasisJpy: number | null }) {
  if (costBasisJpy === null) {
    return (
      <span className="italic text-neutral-600">missing cost basis</span>
    );
  }
  return <span className="text-neutral-200">{formatJpy(costBasisJpy)}</span>;
}

function PriceSnapshotCell({
  snapshot,
}: {
  snapshot: YuyuteiPriceSnapshot | SnkrdunkFloorSnapshot | null;
}) {
  if (!snapshot) {
    return <span className="italic text-neutral-600">missing price</span>;
  }
  return <span className="text-neutral-200">{formatJpy(snapshot.price_jpy)}</span>;
}

function PnlCell({
  pnlJpy,
  pnlPct,
  missingPrice,
  missingCostBasis,
}: {
  pnlJpy: number | null;
  pnlPct: number | null;
  missingPrice: boolean;
  missingCostBasis: boolean;
}) {
  if (missingPrice) {
    return <span className="italic text-neutral-600">missing price</span>;
  }
  if (missingCostBasis) {
    return (
      <span className="italic text-neutral-600">missing cost basis</span>
    );
  }
  if (pnlJpy === null) {
    return <span className="text-neutral-600">—</span>;
  }
  const tone =
    pnlJpy > 0
      ? "text-emerald-400"
      : pnlJpy < 0
        ? "text-rose-400"
        : "text-neutral-400";
  return (
    <span className={tone}>
      {formatSignedJpy(pnlJpy)}{" "}
      <span className="text-neutral-500">({formatSignedPct(pnlPct)})</span>
    </span>
  );
}

function FlagsCell({
  flags,
}: {
  flags: PortfolioValuationItem["flags"];
}) {
  const activeFlags: { key: string; label: string; positive?: boolean }[] = [];
  if (flags.missing_yuyutei_sell) {
    activeFlags.push({ key: "sell", label: "No sell price" });
  }
  if (flags.missing_yuyutei_buy) {
    activeFlags.push({ key: "buy", label: "No buy price" });
  }
  if (flags.missing_snkrdunk_floor) {
    activeFlags.push({ key: "floor", label: "No floor price" });
  }
  if (flags.missing_cost_basis) {
    activeFlags.push({ key: "cost", label: "No cost basis" });
  }
  if (flags.above_target_sell) {
    activeFlags.push({ key: "target", label: "Above target", positive: true });
  }

  if (activeFlags.length === 0) {
    return <span className="text-neutral-600">—</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {activeFlags.map((f) => (
        <span
          key={f.key}
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
            f.positive
              ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
              : "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30"
          }`}
        >
          {f.label}
        </span>
      ))}
    </div>
  );
}

function GradedAdjustedBasisLabel({
  gradedAdjusted,
}: {
  gradedAdjusted: GradedAdjustedValuation;
}) {
  if (gradedAdjusted.basis === "graded_value") {
    return (
      <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-inset ring-violet-500/30">
        Graded value
      </span>
    );
  }
  if (gradedAdjusted.raw_fallback_basis) {
    const label =
      gradedAdjusted.raw_fallback_basis === "snkrdunk_floor"
        ? "SNKRDUNK floor"
        : "Yuyu-Tei sell";
    return (
      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-inset ring-amber-500/30">
        Raw fallback ({label})
      </span>
    );
  }
  return <span className="italic text-neutral-600">no graded value</span>;
}

/** Five <td>s covering the graded-adjusted breakdown for one row - only
 * rendered when the graded_adjusted valuation mode is selected, and never
 * substitutes for the raw retail/liquidation/floor cells (which stay put
 * regardless of mode). `gradedAdjusted` is null when the item is missing
 * from the currently loaded valuation response entirely (e.g. mid-refresh),
 * distinct from a loaded-but-empty graded_adjusted breakdown. */
function GradedAdjustedCells({
  gradedAdjusted,
  latestGradingStatus,
}: {
  gradedAdjusted: GradedAdjustedValuation | null;
  latestGradingStatus: string | null;
}) {
  if (!gradedAdjusted) {
    return (
      <>
        <td className="px-2 py-1.5 text-neutral-600">—</td>
        <td className="px-2 py-1.5 text-neutral-600">—</td>
        <td className="px-2 py-1.5 text-neutral-600">—</td>
        <td className="px-2 py-1.5 text-neutral-600">—</td>
        <td className="px-2 py-1.5 text-neutral-600">—</td>
      </>
    );
  }

  const notReceivedYet =
    gradedAdjusted.basis !== "graded_value" &&
    latestGradingStatus !== null &&
    latestGradingStatus !== "received";

  return (
    <>
      <td className="px-2 py-1.5">
        {gradedAdjusted.value_jpy === null ? (
          <span className="italic text-neutral-600">no graded value</span>
        ) : (
          <span className="text-neutral-200">{formatJpy(gradedAdjusted.value_jpy)}</span>
        )}
      </td>
      <td className="px-2 py-1.5">
        <GradedAdjustedBasisLabel gradedAdjusted={gradedAdjusted} />
        {notReceivedYet && (
          <div className="mt-0.5 text-[10px] italic text-neutral-600">not received</div>
        )}
      </td>
      <td className="px-2 py-1.5 text-neutral-300">
        {gradedAdjusted.final_grade ?? "—"}
      </td>
      <td className="px-2 py-1.5 text-neutral-300">
        {gradedAdjusted.grading_company ?? "—"}
      </td>
      <td className="px-2 py-1.5">
        {gradedAdjusted.value_jpy === null ? (
          <span className="italic text-neutral-600">no graded value</span>
        ) : gradedAdjusted.pnl_jpy === null ? (
          <span className="italic text-neutral-600">missing cost basis</span>
        ) : (
          <PnlCell
            pnlJpy={gradedAdjusted.pnl_jpy}
            pnlPct={gradedAdjusted.pnl_pct}
            missingPrice={false}
            missingCostBasis={false}
          />
        )}
      </td>
    </>
  );
}
