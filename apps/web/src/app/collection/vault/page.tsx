"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { CardVaultTile, type CardVaultTileDensity } from "@/components/ui/CardVaultTile";
import { FILTER_INPUT_CLASS, FILTER_LABEL_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import {
  fetchCards,
  fetchCollectionItems,
  fetchCollectionValuation,
  type Card,
  type CollectionItem,
  type PortfolioValuationItem,
  type ValuationMode,
} from "@/lib/api";
import { cardDisplayName } from "@/lib/format";

type SortKey = "value_desc" | "pnl_desc" | "pnl_asc" | "newest" | "card_code" | "rarity";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "value_desc", label: "Highest value" },
  { value: "pnl_desc", label: "Highest P/L" },
  { value: "pnl_asc", label: "Lowest P/L" },
  { value: "newest", label: "Newest added" },
  { value: "card_code", label: "Card code" },
  { value: "rarity", label: "Rarity" },
];

const DENSITY_OPTIONS: { value: CardVaultTileDensity; label: string }[] = [
  { value: "compact", label: "Compact" },
  { value: "standard", label: "Standard" },
  { value: "showcase", label: "Showcase" },
];

const ALL_OPTION = { value: "", label: "All" };

interface VaultRow {
  item: CollectionItem;
  valuation: PortfolioValuationItem | null;
  card: Card | null;
}

function valueAndPnl(valuation: PortfolioValuationItem | null, mode: ValuationMode) {
  if (!valuation) return { value: null as number | null, pnlJpy: null as number | null, pnlPct: null as number | null };
  if (mode === "graded_adjusted") {
    return {
      value: valuation.graded_adjusted.value_jpy,
      pnlJpy: valuation.graded_adjusted.pnl_jpy,
      pnlPct: valuation.graded_adjusted.pnl_pct,
    };
  }
  return {
    value: valuation.valuations.market_floor_value_jpy,
    pnlJpy: valuation.valuations.pnl_vs_market_floor_jpy,
    pnlPct: valuation.valuations.pnl_vs_market_floor_pct,
  };
}

export default function CollectionVaultPage() {
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [listStatus, setListStatus] = useState<"loading" | "error" | "ready">("loading");

  const [valuationItems, setValuationItems] = useState<PortfolioValuationItem[]>([]);
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");

  const [cards, setCards] = useState<Card[]>([]);

  const [search, setSearch] = useState("");
  const [setCodeFilter, setSetCodeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [variantFilter, setVariantFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [conditionFilter, setConditionFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("value_desc");
  const [density, setDensity] = useState<CardVaultTileDensity>("standard");

  function refreshList() {
    fetchCollectionItems({ limit: 500 })
      .then((data) => {
        setItems(data.items);
        setListStatus("ready");
      })
      .catch(() => setListStatus("error"));
  }

  function refreshValuation(mode: ValuationMode = valuationMode) {
    fetchCollectionValuation(mode)
      .then((data) => setValuationItems(data.items))
      .catch(() => setValuationItems([]));
  }

  useEffect(() => {
    refreshList();
    refreshValuation();
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleValuationModeChange(mode: ValuationMode) {
    setValuationMode(mode);
    refreshValuation(mode);
  }

  const cardsById = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const valuationByItemId = useMemo(
    () => new Map(valuationItems.map((v) => [v.collection_item_id, v])),
    [valuationItems],
  );

  const rows: VaultRow[] = useMemo(
    () =>
      items.map((item) => ({
        item,
        valuation: valuationByItemId.get(item.id) ?? null,
        card: cardsById.get(item.card_id) ?? null,
      })),
    [items, valuationByItemId, cardsById],
  );

  const setCodeOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.set_code))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const rarityOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.rarity))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const variantOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.variant).filter((v): v is string => !!v))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const statusOptions = useMemo(() => {
    const values = Array.from(new Set(items.map((i) => i.status))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const conditionOptions = useMemo(() => {
    const values = Array.from(
      new Set(items.map((i) => i.condition_label).filter((v): v is string => !!v)),
    ).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [items]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter(({ item }) => {
      if (q) {
        const haystack = `${item.card_code} ${cardDisplayName(item)}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (setCodeFilter && item.set_code !== setCodeFilter) return false;
      if (rarityFilter && item.rarity !== rarityFilter) return false;
      if (variantFilter && (item.variant ?? "") !== variantFilter) return false;
      if (statusFilter && item.status !== statusFilter) return false;
      if (conditionFilter && (item.condition_label ?? "") !== conditionFilter) return false;
      return true;
    });
  }, [rows, search, setCodeFilter, rarityFilter, variantFilter, statusFilter, conditionFilter]);

  const sortedRows = useMemo(() => {
    const arr = [...filteredRows];
    switch (sortKey) {
      case "value_desc":
        arr.sort(
          (a, b) =>
            (valueAndPnl(b.valuation, valuationMode).value ?? -Infinity) -
            (valueAndPnl(a.valuation, valuationMode).value ?? -Infinity),
        );
        break;
      case "pnl_desc":
        arr.sort(
          (a, b) =>
            (valueAndPnl(b.valuation, valuationMode).pnlJpy ?? -Infinity) -
            (valueAndPnl(a.valuation, valuationMode).pnlJpy ?? -Infinity),
        );
        break;
      case "pnl_asc":
        arr.sort(
          (a, b) =>
            (valueAndPnl(a.valuation, valuationMode).pnlJpy ?? Infinity) -
            (valueAndPnl(b.valuation, valuationMode).pnlJpy ?? Infinity),
        );
        break;
      case "newest":
        arr.sort((a, b) => new Date(b.item.created_at).getTime() - new Date(a.item.created_at).getTime());
        break;
      case "card_code":
        arr.sort((a, b) => a.item.card_code.localeCompare(b.item.card_code));
        break;
      case "rarity":
        arr.sort((a, b) => a.item.rarity.localeCompare(b.item.rarity));
        break;
    }
    return arr;
  }, [filteredRows, sortKey, valuationMode]);

  const gridColsClass =
    density === "showcase"
      ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
      : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Collection Vault"
          description={
            <Link href="/collection" className="text-sky-400 hover:text-sky-300">
              Table View →
            </Link>
          }
          actions={
            listStatus === "ready" && (
              <span className="mono tabular text-sm text-text-muted">
                {sortedRows.length} of {items.length} card{items.length === 1 ? "" : "s"}
              </span>
            )
          }
        />

        <div className="mb-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search card code or name…"
              className={`w-64 ${FILTER_INPUT_CLASS}`}
            />
            <label className={FILTER_LABEL_CLASS}>
              Set
              <select
                value={setCodeFilter}
                onChange={(e) => setSetCodeFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {setCodeOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={FILTER_LABEL_CLASS}>
              Rarity
              <select
                value={rarityFilter}
                onChange={(e) => setRarityFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {rarityOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={FILTER_LABEL_CLASS}>
              Variant
              <select
                value={variantFilter}
                onChange={(e) => setVariantFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {variantOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={FILTER_LABEL_CLASS}>
              Status
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {statusOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={FILTER_LABEL_CLASS}>
              Condition
              <select
                value={conditionFilter}
                onChange={(e) => setConditionFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {conditionOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1">
              {(["raw_market", "graded_adjusted"] as ValuationMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => handleValuationModeChange(mode)}
                  className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                    valuationMode === mode
                      ? "bg-accent-gold text-black/80 ring-accent-gold"
                      : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                  }`}
                >
                  {mode === "raw_market" ? "Raw market" : "Graded adjusted"}
                </button>
              ))}
            </div>

            <label className={FILTER_LABEL_CLASS}>
              Sort
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className={FILTER_INPUT_CLASS}
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex gap-1">
              {DENSITY_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setDensity(o.value)}
                  className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                    density === o.value
                      ? "bg-accent-gold text-black/80 ring-accent-gold"
                      : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <SavedViewBar
          routePath="/collection/vault"
          viewType="collection_vault"
          scope="collector"
          currentFilters={{
            search,
            setCodeFilter,
            rarityFilter,
            variantFilter,
            statusFilter,
            conditionFilter,
            valuationMode,
            sortKey,
            density,
          }}
          onApply={(filters) => {
            if (typeof filters.search === "string") setSearch(filters.search);
            if (typeof filters.setCodeFilter === "string") setSetCodeFilter(filters.setCodeFilter);
            if (typeof filters.rarityFilter === "string") setRarityFilter(filters.rarityFilter);
            if (typeof filters.variantFilter === "string") setVariantFilter(filters.variantFilter);
            if (typeof filters.statusFilter === "string") setStatusFilter(filters.statusFilter);
            if (typeof filters.conditionFilter === "string") setConditionFilter(filters.conditionFilter);
            if (filters.valuationMode === "raw_market" || filters.valuationMode === "graded_adjusted") {
              handleValuationModeChange(filters.valuationMode);
            }
            if (typeof filters.sortKey === "string") setSortKey(filters.sortKey as SortKey);
            if (
              filters.density === "compact" ||
              filters.density === "standard" ||
              filters.density === "showcase"
            ) {
              setDensity(filters.density);
            }
          }}
        />

        {listStatus === "loading" && <LoadingState>Loading your vault…</LoadingState>}

        {listStatus === "error" && (
          <ErrorState>Failed to load your collection from the API. Is the backend running?</ErrorState>
        )}

        {listStatus === "ready" && items.length === 0 && (
          <EmptyState>No cards in your vault yet. Add cards to your collection first.</EmptyState>
        )}

        {listStatus === "ready" && items.length > 0 && sortedRows.length === 0 && (
          <EmptyState>No cards match the selected filters.</EmptyState>
        )}

        {listStatus === "ready" && sortedRows.length > 0 && (
          <div className={`grid gap-3 ${gridColsClass}`}>
            {sortedRows.map(({ item, valuation, card }) => {
              const { value, pnlJpy, pnlPct } = valueAndPnl(valuation, valuationMode);
              return (
                <CardVaultTile
                  key={item.id}
                  cardId={item.card_id}
                  cardCode={item.card_code}
                  name={cardDisplayName(item)}
                  imageUrl={card?.image_url ?? null}
                  rarity={item.rarity}
                  variant={item.variant}
                  setCode={item.set_code}
                  valueJpy={value}
                  mode={valuationMode}
                  quantity={item.quantity}
                  conditionLabel={item.condition_label}
                  pnlJpy={pnlJpy}
                  pnlPct={pnlPct}
                  targetSellJpy={item.target_sell_price_jpy}
                  targetHit={valuation?.flags.above_target_sell ?? false}
                  statusPill={<CollectionStatusBadge status={item.status} />}
                  gradingBadge={
                    valuation?.grading.has_grading_submission ? (
                      <GradingStatusBadge status={valuation.grading.latest_status ?? "planned"} />
                    ) : undefined
                  }
                  density={density}
                />
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
