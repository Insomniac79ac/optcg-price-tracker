"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionImportExport } from "@/components/CollectionImportExport";
import { CollectionItemGroupsCell } from "@/components/CollectionItemGroupsCell";
import { CollectionItemTagsCell } from "@/components/CollectionItemTagsCell";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { CollectionValuationSummary } from "@/components/CollectionValuationSummary";
import { CollectorTagsGroupsManager } from "@/components/CollectorTagsGroupsManager";
import { FormField } from "@/components/FormField";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { PaginationControls } from "@/components/PaginationControls";
import type { HistoryTimeframe } from "@/components/PortfolioValuationHistoryChart";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { ConfirmActionModal } from "@/components/ui/ConfirmActionModal";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS, FILTER_LABEL_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { PriceCell } from "@/components/ui/PriceCell";
import { QuickActionBar } from "@/components/ui/QuickActionBar";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { VariantBadge } from "@/components/ui/VariantBadge";
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
import { cardDisplayName } from "@/lib/format";

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
const LIMIT_OPTIONS = [25, 50, 100, 200] as const;

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

  // filteredItems is derived client-side from a single (up to 500-item)
  // server fetch - see refreshList() below - so pagination here paginates
  // that already-filtered client-side array rather than re-fetching pages
  // from the backend.
  const [pageLimit, setPageLimit] = useState(100);
  const [pageOffset, setPageOffset] = useState(0);

  const [allTags, setAllTags] = useState<CollectorTag[]>([]);
  const [allGroups, setAllGroups] = useState<CollectorGroup[]>([]);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CollectionItem | null>(null);

  const formSectionRef = useRef<HTMLElement>(null);
  const importExportRef = useRef<HTMLDivElement>(null);

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

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filtered set is otherwise almost certainly out of range for the new
  // one.
  useEffect(() => {
    setPageOffset(0);
  }, [filteredItems, pageLimit]);

  const pagedItems = useMemo(
    () => filteredItems.slice(pageOffset, pageOffset + pageLimit),
    [filteredItems, pageOffset, pageLimit],
  );

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
    setActionError(null);
    setPendingDeleteId(item.id);
    try {
      await deleteCollectionItem(item.id);
      if (editingId === item.id) cancelEdit();
      setDeleteTarget(null);
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
        <PageHeader
          title="Collection"
          description={
            <span className="flex flex-wrap gap-3">
              <Link href="/analytics/collection" className="text-sky-400 hover:text-sky-300">
                Analytics →
              </Link>
              <Link href="/analytics/sell-decisions" className="text-sky-400 hover:text-sky-300">
                Sell decisions →
              </Link>
              <Link href="/grading" className="text-sky-400 hover:text-sky-300">
                Grading →
              </Link>
              <Link href="/analytics/grading" className="text-sky-400 hover:text-sky-300">
                Grading ROI →
              </Link>
              <Link href="/analytics/portfolio-risk" className="text-sky-400 hover:text-sky-300">
                Portfolio Risk →
              </Link>
              <Link href="/wishlist" className="text-sky-400 hover:text-sky-300">
                Wishlist →
              </Link>
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              {listStatus === "ready" && (
                <span className="mono tabular text-sm text-text-muted">
                  {total} item{total === 1 ? "" : "s"}
                </span>
              )}
              <div className="flex gap-1">
                <span className="rounded-control bg-accent-gold px-2.5 py-1 text-xs font-medium text-black/80 ring-1 ring-inset ring-accent-gold">
                  Table View
                </span>
                <Link
                  href="/collection/vault"
                  className="rounded-control bg-bg-surface px-2.5 py-1 text-xs font-medium text-text-secondary ring-1 ring-inset ring-border-default hover:text-text-primary"
                >
                  Vault View →
                </Link>
              </div>
            </div>
          }
        />

        <QuickActionBar
          actions={[
            { label: "Vault View", href: "/collection/vault" },
            { label: "Collection Analytics", href: "/analytics/collection" },
            {
              label: "Add Item",
              onClick: () => formSectionRef.current?.scrollIntoView({ behavior: "smooth" }),
            },
            {
              label: "Import / Export",
              onClick: () => importExportRef.current?.scrollIntoView({ behavior: "smooth" }),
            },
          ]}
        />

        <div ref={importExportRef}>
          <CollectionImportExport
            onImported={() => {
              refreshList();
              refreshSummary();
              refreshValuation();
            }}
          />
        </div>

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
          <div className="panel mb-6 flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="text-xs uppercase tracking-wide text-text-muted">
              By status
            </span>
            {STATUS_OPTIONS.map((s) => (
              <span
                key={s}
                className="flex items-center gap-1.5 rounded border border-border-default bg-bg-page px-2 py-1"
              >
                <CollectionStatusBadge status={s} />
                <span className="text-xs text-text-secondary">
                  {summary.items_by_status[s] ?? 0}
                </span>
              </span>
            ))}
          </div>
        )}

        <section ref={formSectionRef} className="panel mb-6 p-4">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">
            {editingId !== null ? "Edit collection item" : "Add collection item"}
          </h2>

          {formError && (
            <div className="mb-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
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
                  className="mb-1 w-full rounded border border-border-default bg-bg-page px-2 py-1 text-xs text-text-primary placeholder:text-text-faint"
                />
                <select
                  value={form.card_id}
                  onChange={(e) => updateField("card_id", e.target.value)}
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
                />
              </FormField>

              <FormField label="Purchase date">
                <input
                  type="date"
                  value={form.purchase_date}
                  onChange={(e) => updateField("purchase_date", e.target.value)}
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
                />
              </FormField>

              <FormField label="Status">
                <select
                  value={form.status}
                  onChange={(e) => updateField("status", e.target.value)}
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
                  className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
                />
              </FormField>
            </div>

            <div className="flex gap-2">
              <ActionButton variant="primary" type="submit" disabled={saving}>
                {saving
                  ? "Saving…"
                  : editingId !== null
                    ? "Update item"
                    : "Add item"}
              </ActionButton>
              {editingId !== null && (
                <ActionButton type="button" onClick={cancelEdit} disabled={saving}>
                  Cancel
                </ActionButton>
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
                  className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                    statusFilter === f.value
                      ? "bg-accent-gold/15 text-accent-gold ring-accent-gold/40"
                      : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
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
              className={FILTER_INPUT_CLASS}
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
            <label className={`${FILTER_LABEL_CLASS} rounded-control border border-border-default bg-bg-surface px-2 py-1`}>
              <input
                type="checkbox"
                checked={missingPricesOnly}
                onChange={(e) => setMissingPricesOnly(e.target.checked)}
                className="rounded border-border-default bg-bg-page"
              />
              Missing prices
            </label>
            <label className={`${FILTER_LABEL_CLASS} rounded-control border border-border-default bg-bg-surface px-2 py-1`}>
              <input
                type="checkbox"
                checked={missingCostBasisOnly}
                onChange={(e) => setMissingCostBasisOnly(e.target.checked)}
                className="rounded border-border-default bg-bg-page"
              />
              Missing cost basis
            </label>
            <label className={`${FILTER_LABEL_CLASS} rounded-control border border-border-default bg-bg-surface px-2 py-1`}>
              <input
                type="checkbox"
                checked={aboveTargetOnly}
                onChange={(e) => setAboveTargetOnly(e.target.checked)}
                className="rounded border-border-default bg-bg-page"
              />
              Above target sell
            </label>
            {items.length > 0 && (
              <span className="text-xs text-text-faint">
                {filteredItems.length} of {items.length} shown
              </span>
            )}
          </div>
        </div>

        <SavedViewBar
          routePath="/collection"
          viewType="collection"
          scope="collector"
          currentFilters={{
            statusFilter,
            cardCodeFilter,
            conditionFilter,
            setCodeFilter,
            rarityFilter,
            tagFilter,
            groupFilter,
            missingPricesOnly,
            missingCostBasisOnly,
            aboveTargetOnly,
          }}
          onApply={(filters) => {
            if (typeof filters.statusFilter === "string") setStatusFilter(filters.statusFilter);
            if (typeof filters.cardCodeFilter === "string") {
              setCardCodeFilter(filters.cardCodeFilter);
              setCardCodeInput(filters.cardCodeFilter);
            }
            if (typeof filters.conditionFilter === "string") setConditionFilter(filters.conditionFilter);
            if (typeof filters.setCodeFilter === "string") setSetCodeFilter(filters.setCodeFilter);
            if (typeof filters.rarityFilter === "string") setRarityFilter(filters.rarityFilter);
            if (typeof filters.tagFilter === "string") setTagFilter(filters.tagFilter);
            if (typeof filters.groupFilter === "string") setGroupFilter(filters.groupFilter);
            if (typeof filters.missingPricesOnly === "boolean") setMissingPricesOnly(filters.missingPricesOnly);
            if (typeof filters.missingCostBasisOnly === "boolean") setMissingCostBasisOnly(filters.missingCostBasisOnly);
            if (typeof filters.aboveTargetOnly === "boolean") setAboveTargetOnly(filters.aboveTargetOnly);
            setPageOffset(0);
          }}
        />

        {actionError && (
          <div className="mb-3 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
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
          <DataTableShell>
            <table className="data-table">
              <thead>
                <tr>
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
                {pagedItems.map((item) => {
                  const v = valuationByItemId.get(item.id);
                  return (
                    <tr key={item.id}>
                      <td className="px-2 py-1.5 font-mono text-text-secondary">
                        {item.card_code}
                      </td>
                      <td className="px-2 py-1.5 font-medium text-text-primary">
                        {cardDisplayName(item)}
                      </td>
                      <td className="px-2 py-1.5 text-text-secondary">
                        {item.set_code}
                      </td>
                      <td className="px-2 py-1.5">
                        <RarityBadge rarity={item.rarity} />
                      </td>
                      <td className="px-2 py-1.5">
                        <VariantBadge variant={item.variant} />
                      </td>
                      <td className="mono tabular px-2 py-1.5 text-text-primary">
                        {item.quantity}
                      </td>
                      <td className="px-2 py-1.5 text-text-secondary">
                        {item.condition_label ?? "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        <PriceCell valueJpy={item.purchase_price_jpy} size="sm" />
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
                      <td className="px-2 py-1.5">
                        <PriceCell valueJpy={item.target_sell_price_jpy} size="sm" />
                      </td>
                      <td className="px-2 py-1.5">
                        {v ? (
                          <FlagsCell flags={v.flags} />
                        ) : (
                          <span className="text-text-faint">—</span>
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
                          <span className="text-text-faint">—</span>
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
                            onClick={() => setDeleteTarget(item)}
                            disabled={pendingDeleteId === item.id}
                            className="text-xs font-medium text-signal-red hover:text-signal-red disabled:opacity-50"
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
          </DataTableShell>
        )}

        {listStatus === "ready" && filteredItems.length > 0 && (
          <div className="mt-3">
            <PaginationControls
              offset={pageOffset}
              limit={pageLimit}
              total={filteredItems.length}
              onOffsetChange={setPageOffset}
              limitOptions={LIMIT_OPTIONS}
              onLimitChange={setPageLimit}
            />
          </div>
        )}
      </main>

      <ConfirmActionModal
        open={deleteTarget !== null}
        title="Remove from collection"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.quantity}x ${deleteTarget.card_code} — ${cardDisplayName(deleteTarget)} from your collection? This cannot be undone.`
            : undefined
        }
        confirmLabel={pendingDeleteId !== null ? "Deleting…" : "Delete"}
        pending={pendingDeleteId !== null}
        onConfirm={() => deleteTarget && handleDelete(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />
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
    <label className={FILTER_LABEL_CLASS}>
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={FILTER_INPUT_CLASS}
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
      <span className="italic text-text-faint">missing cost basis</span>
    );
  }
  return <PriceCell valueJpy={costBasisJpy} size="sm" />;
}

function PriceSnapshotCell({
  snapshot,
}: {
  snapshot: YuyuteiPriceSnapshot | SnkrdunkFloorSnapshot | null;
}) {
  if (!snapshot) {
    return <span className="italic text-text-faint">missing price</span>;
  }
  // No source/priceType passed here - the column header already names the
  // basis (Yuyu-Tei sell/buy, SNKRDUNK floor), so repeating it as a chip on
  // every row would be redundant noise in an already-dense table. Still
  // gets PriceCell's mono/tabular formatting and stale badge.
  return <PriceCell valueJpy={snapshot.price_jpy} observedAt={snapshot.observed_at} size="sm" />;
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
    return <span className="italic text-text-faint">missing price</span>;
  }
  if (missingCostBasis) {
    return (
      <span className="italic text-text-faint">missing cost basis</span>
    );
  }
  return <PriceCell valueJpy={pnlJpy} percent={pnlPct} signed size="sm" />;
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
    return <span className="text-text-faint">—</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {activeFlags.map((f) => (
        <span
          key={f.key}
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
            f.positive
              ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
              : "bg-neutral-500/15 text-text-secondary ring-neutral-500/30"
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
      <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[11px] font-medium text-violet-300 ring-1 ring-inset ring-violet-500/30">
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
      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-signal-warning ring-1 ring-inset ring-amber-500/30">
        Raw fallback ({label})
      </span>
    );
  }
  return <span className="italic text-text-faint">no graded value</span>;
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
        <td className="px-2 py-1.5 text-text-faint">—</td>
        <td className="px-2 py-1.5 text-text-faint">—</td>
        <td className="px-2 py-1.5 text-text-faint">—</td>
        <td className="px-2 py-1.5 text-text-faint">—</td>
        <td className="px-2 py-1.5 text-text-faint">—</td>
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
          <span className="italic text-text-faint">no graded value</span>
        ) : (
          // No `mode` prop here - the adjacent "Graded-adj. basis" column
          // (GradedAdjustedBasisLabel below) already names the basis, so a
          // second badge in this cell would just repeat it.
          <PriceCell valueJpy={gradedAdjusted.value_jpy} size="sm" />
        )}
      </td>
      <td className="px-2 py-1.5">
        <GradedAdjustedBasisLabel gradedAdjusted={gradedAdjusted} />
        {notReceivedYet && (
          <div className="mt-0.5 text-[11px] italic text-text-faint">not received</div>
        )}
      </td>
      <td className="px-2 py-1.5 text-text-secondary">
        {gradedAdjusted.final_grade ?? "—"}
      </td>
      <td className="px-2 py-1.5 text-text-secondary">
        {gradedAdjusted.grading_company ?? "—"}
      </td>
      <td className="px-2 py-1.5">
        {gradedAdjusted.value_jpy === null ? (
          <span className="italic text-text-faint">no graded value</span>
        ) : gradedAdjusted.pnl_jpy === null ? (
          <span className="italic text-text-faint">missing cost basis</span>
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
