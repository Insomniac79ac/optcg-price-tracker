"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionItemTagsCell } from "@/components/CollectionItemTagsCell";
import { FormField } from "@/components/FormField";
import { PriceTypeBadge } from "@/components/PriceTypeBadge";
import { SourceBadge } from "@/components/SourceBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { CardActivityPanel } from "@/components/ui/CardActivityPanel";
import { CardIdentityBlock } from "@/components/ui/CardIdentityBlock";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { CardPricePanel, type PriceLine } from "@/components/ui/CardPricePanel";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { GradingSummaryPanel } from "@/components/ui/GradingSummaryPanel";
import { MarketIndexValue } from "@/components/ui/MarketIndexValue";
import { OwnershipSummaryPanel } from "@/components/ui/OwnershipSummaryPanel";
import { SourceEvidenceBadge } from "@/components/ui/SourceEvidenceBadge";
import { accentForVariant } from "@/components/ui/VariantBadge";
import { WishlistSummaryPanel } from "@/components/ui/WishlistSummaryPanel";
import { StockStatusBadge } from "@/components/StockStatusBadge";
import {
  COLLECTION_STATUS_OPTIONS,
  WISHLIST_PRIORITIES,
  type Card,
  type CollectionItem,
  type CollectionItemInput,
  type CollectorActivityEvent,
  type CollectorNote,
  type CollectorTag,
  type PortfolioValuationItem,
  type PriceObservation,
  type SourceCardMapping,
  type ValuationMode,
  type WishlistItem,
  type WishlistPriority,
  assignCardTag,
  createCollectionItem,
  createWishlistItem,
  fetchAdminSourceMappings,
  fetchCard,
  fetchCardPrices,
  fetchCollectionItems,
  fetchCollectionValuation,
  fetchCollectorActivity,
  fetchCardMarketIndex,
  fetchCollectorNotes,
  fetchCollectorTags,
  fetchWishlistItems,
  unassignCardTag,
  type MarketIndex,
} from "@/lib/api";
import { cardDisplayName, formatDate, formatDateTime, formatJpy } from "@/lib/format";

// Dynamically imported (recharts is a sizeable chunk) so pages that never
// render a price chart - most of this app - don't pay for it. ssr: false
// sidesteps recharts' well-known SSR/hydration mismatch (it measures its
// container via ResizeObserver, which needs a real browser).
const PriceChart = dynamic(
  () => import("@/components/PriceChart").then((mod) => mod.PriceChart),
  { ssr: false, loading: () => <LoadingState>Loading chart…</LoadingState> },
);

type Status = "loading" | "error" | "ready";

interface KeyPriceLine {
  label: string;
  source: string;
  priceType: string;
}

// Labels spell out what each source price actually is (design brief Phase
// 9 - "do not present Yuyu-Tei buy as the card's primary value" / "do not
// present SNKRDUNK floor as a completed sale"): these are supporting detail
// beneath the Market Index, not the Market Index's own inputs restated.
// referenceType matches app.services.market_index's reference_type strings,
// used to look up the matching MarketIndexSourceValue for its evidence
// badge (see keyPriceLines below).
const KEY_PRICE_LINES: (KeyPriceLine & { referenceType: string; auxiliary?: boolean })[] = [
  { label: "Yuyu-Tei sell", source: "yuyutei", priceType: "sell", referenceType: "retail_sell" },
  {
    label: "Yuyu-Tei buy (dealer buy / liquidity)",
    source: "yuyutei",
    priceType: "buy",
    referenceType: "dealer_buy",
    auxiliary: true,
  },
  {
    label: "SNKRDUNK sold (reference)",
    source: "snkrdunk",
    priceType: "sold",
    referenceType: "transaction_median",
  },
  {
    label: "SNKRDUNK floor (listing, not a sale)",
    source: "snkrdunk",
    priceType: "floor",
    referenceType: "listing_floor",
  },
];

function keyPriceLines(
  prices: PriceObservation[],
  marketIndex: MarketIndex | null,
): PriceLine[] {
  return KEY_PRICE_LINES.map((line) => {
    const observation = latestFor(prices, line.source, line.priceType);
    const sourceValues = line.auxiliary
      ? marketIndex?.auxiliary_values
      : marketIndex?.source_values;
    const sourceValue = sourceValues?.find(
      (v) => v.source === line.source && v.reference_type === line.referenceType,
    );

    return {
      label: line.label,
      source: line.source,
      priceType: line.priceType,
      valueJpy: observation?.price_jpy ?? null,
      observedAt: observation?.observed_at ?? null,
      note: sourceValue ? <SourceEvidenceBadge value={sourceValue} /> : undefined,
    };
  });
}

function latestFor(
  prices: PriceObservation[],
  source: string,
  priceType: string,
): PriceObservation | null {
  const matches = prices.filter(
    (p) => p.source === source && p.price_type === priceType,
  );
  if (matches.length === 0) return null;
  return matches.reduce((latest, p) =>
    new Date(p.observed_at).getTime() > new Date(latest.observed_at).getTime()
      ? p
      : latest,
  );
}

export default function CardDetailPage() {
  const params = useParams<{ id: string }>();
  const cardId = params.id;

  const [card, setCard] = useState<Card | null>(null);
  const [prices, setPrices] = useState<PriceObservation[]>([]);
  const [status, setStatus] = useState<Status>("loading");

  const [marketIndex, setMarketIndex] = useState<MarketIndex | null>(null);
  const [marketIndexStatus, setMarketIndexStatus] = useState<Status>("loading");

  const [collectionItems, setCollectionItems] = useState<CollectionItem[]>([]);
  const [collectionStatus, setCollectionStatus] = useState<Status>("loading");

  const [wishlistItems, setWishlistItems] = useState<WishlistItem[]>([]);
  const [wishlistStatus, setWishlistStatus] = useState<Status>("loading");

  const [allTags, setAllTags] = useState<CollectorTag[]>([]);
  const [tagError, setTagError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all([fetchCard(cardId), fetchCardPrices(cardId)])
      .then(([cardData, priceData]) => {
        if (cancelled) return;
        setCard(cardData);
        setPrices(priceData);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [cardId]);

  useEffect(() => {
    let cancelled = false;
    setMarketIndexStatus("loading");
    fetchCardMarketIndex(cardId)
      .then((data) => {
        if (cancelled) return;
        setMarketIndex(data);
        setMarketIndexStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setMarketIndexStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [cardId]);

  useEffect(() => {
    fetchCollectorTags()
      .then(setAllTags)
      .catch(() => setAllTags([]));
  }, []);

  async function handleAssignTag(tagId: number) {
    setTagError(null);
    try {
      const updated = await assignCardTag(Number(cardId), tagId);
      setCard(updated);
    } catch {
      setTagError("Failed to assign tag.");
    }
  }

  async function handleUnassignTag(tagId: number) {
    setTagError(null);
    try {
      const updated = await unassignCardTag(Number(cardId), tagId);
      setCard(updated);
    } catch {
      setTagError("Failed to remove tag.");
    }
  }

  function refreshCollectionItems() {
    fetchCollectionItems({ card_id: Number(cardId) })
      .then((data) => {
        setCollectionItems(data.items);
        setCollectionStatus("ready");
      })
      .catch(() => setCollectionStatus("error"));
  }

  useEffect(() => {
    refreshCollectionItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId]);

  function refreshWishlistItems(cardCode: string) {
    fetchWishlistItems({ card_code: cardCode })
      .then((data) => {
        setWishlistItems(data.items.filter((i) => i.status !== "removed"));
        setWishlistStatus("ready");
      })
      .catch(() => setWishlistStatus("error"));
  }

  useEffect(() => {
    if (card) refreshWishlistItems(card.card_code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.card_code]);

  // Ownership valuation (cost basis/current value/P&L) - same source
  // /collection itself uses, so the numbers never disagree.
  const [valuationMode] = useState<ValuationMode>("raw_market");
  const [valuationItems, setValuationItems] = useState<PortfolioValuationItem[]>([]);

  useEffect(() => {
    fetchCollectionValuation(valuationMode)
      .then((data) => setValuationItems(data.items.filter((i) => i.card_id === Number(cardId))))
      .catch(() => setValuationItems([]));
  }, [cardId, valuationMode]);

  // Notes/activity for this card.
  const [notes, setNotes] = useState<CollectorNote[]>([]);
  const [activity, setActivity] = useState<CollectorActivityEvent[]>([]);

  function refreshNotes() {
    fetchCollectorNotes({ card_id: Number(cardId) })
      .then((data) => setNotes(data.items))
      .catch(() => setNotes([]));
  }

  useEffect(() => {
    refreshNotes();
    fetchCollectorActivity({ card_id: Number(cardId) })
      .then((data) => setActivity(data.events))
      .catch(() => setActivity([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId]);

  // Admin-only source mappings mini panel - only fetched (and only ever
  // shown) for a role="admin" session, same gate as every other admin-only
  // UI element in this app (see src/lib/adminSession.ts).
  const { data: session } = useSession();
  const isAdmin = session?.user?.role === "admin";
  const [adminMappings, setAdminMappings] = useState<SourceCardMapping[]>([]);

  useEffect(() => {
    if (!isAdmin || !card) return;
    fetchAdminSourceMappings({ card_code: card.card_code })
      .then((data) => setAdminMappings(data.items))
      .catch(() => setAdminMappings([]));
  }, [isAdmin, card?.card_code]);

  const gradingSubmissions = collectionItems.flatMap((item) => item.grading_submissions);

  const latestFirst = prices
    .slice()
    .sort(
      (a, b) =>
        new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime(),
    );

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        {/* /dashboard is a signed-in-only route (see proxyGuard.ts) - linking
            there from a page every anonymous visitor can reach would bounce
            them straight to /sign-in. /cards is this app's actual public
            "came from browsing the catalogue" entry point (collector-first
            redesign audit, Phase 7). */}
        <Link
          href="/cards"
          className="mb-4 inline-block text-sm text-text-secondary hover:text-text-primary"
        >
          ← Back to Cards
        </Link>

        {status === "loading" && <LoadingState>Loading card…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load this card from the API.</ErrorState>
        )}

        {status === "ready" && card && (
          // flex + explicit order (not space-y) so mobile can prioritize the
          // price panel above ownership/wishlist/grading while desktop keeps
          // the original document order (see design brief "Card detail" -
          // mobile: image/identity, then price source, then ownership panels;
          // admin panel stays lowest-priority on every breakpoint).
          <div className="flex flex-col gap-6">
            {/* 1. Hero - image + identity + compact metadata grid + effect/trigger text */}
            <div className="panel flex flex-col gap-4 p-4 sm:flex-row">
              <CardImageFrame
                imageUrl={card.image_url}
                alt={cardDisplayName(card)}
                cardCode={card.card_code}
                rarity={card.rarity}
                setCode={card.set_code}
                accent={accentForVariant(card.variant)}
                size="lg"
              />
              <div className="flex-1 space-y-3">
                <CardIdentityBlock
                  cardCode={card.card_code}
                  name={cardDisplayName(card)}
                  nameSecondary={card.name_en && card.name_jp ? card.name_jp : null}
                  rarity={card.rarity}
                  variant={card.variant}
                  language={card.language}
                  setCode={card.set_code}
                  asHeading
                />
                <MarketIndexSection status={marketIndexStatus} index={marketIndex} />
                <CardMetadataGrid card={card} />
                <CardEffectText card={card} />
              </div>
            </div>

            <div className="order-3 rounded-panel border border-border-default bg-bg-surface p-4 lg:order-none">
              <h2 className="mb-2 text-sm font-semibold text-text-primary">Card tags</h2>
              {tagError && (
                <div className="mb-2 rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
                  {tagError}
                </div>
              )}
              <CollectionItemTagsCell
                assigned={card.tags}
                available={allTags}
                onAssign={handleAssignTag}
                onUnassign={handleUnassignTag}
              />
            </div>

            {/* 2. Ownership / wishlist / grading */}
            <div className="order-2 grid grid-cols-1 gap-4 lg:order-none lg:grid-cols-3">
              {collectionStatus === "ready" ? (
                <OwnershipSummaryPanel
                  items={collectionItems}
                  valuationItems={valuationItems}
                  valuationMode={valuationMode}
                  onChanged={refreshCollectionItems}
                  addAction={<QuickAddForm cardId={card.id} onAdded={refreshCollectionItems} />}
                />
              ) : (
                <div className="panel p-4">
                  <p className="text-sm text-text-muted">
                    {collectionStatus === "error"
                      ? "Failed to load collection status."
                      : "Loading collection status…"}
                  </p>
                </div>
              )}

              {wishlistStatus === "ready" ? (
                <WishlistSummaryPanel
                  items={wishlistItems}
                  addAction={
                    <QuickAddWishlistForm
                      cardId={card.id}
                      onAdded={() => refreshWishlistItems(card.card_code)}
                    />
                  }
                />
              ) : (
                <div className="panel p-4">
                  <p className="text-sm text-text-muted">
                    {wishlistStatus === "error"
                      ? "Failed to load wishlist status."
                      : "Loading wishlist status…"}
                  </p>
                </div>
              )}

              <GradingSummaryPanel submissions={gradingSubmissions} />
            </div>

            {/* 3. Price source panel - highest-priority data panel on mobile,
                right after the hero (design brief - "price source panel
                next"), same position as always on desktop. */}
            <div className="order-1 lg:order-none">
              <CardPricePanel lines={keyPriceLines(prices, marketIndex)} />
            </div>

            {/* 5. Notes/activity */}
            <div className="order-5 lg:order-none">
              <CardActivityPanel
                cardId={card.id}
                notes={notes}
                activity={activity}
                onNoteAdded={refreshNotes}
              />
            </div>

            {/* 6. Admin mini-panel - only rendered for admin-token holders;
                lowest-priority panel on mobile (design brief - "admin mini
                panel should be collapsed or lower priority"). */}
            {isAdmin && (
              <div className="order-6 lg:order-none">
                <AdminSourceMappingsMiniPanel mappings={adminMappings} />
              </div>
            )}

            <div className="order-7 lg:order-none">
              <h2 className="mb-2 text-sm font-semibold text-text-primary">
                Price history
              </h2>
              <PriceChart observations={prices} />
            </div>

            <div className="order-8 lg:order-none">
              <h2 className="mb-2 text-sm font-semibold text-text-primary">
                Price observations
              </h2>
              <DataTableShell
                isEmpty={latestFirst.length === 0}
                emptyLabel="No price observations yet."
                minWidth={640}
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Observed at</th>
                      <th>Source</th>
                      <th>Type</th>
                      <th className="text-right">Price</th>
                      <th>Condition</th>
                      <th>Stock</th>
                      <th className="text-right">Listings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latestFirst.map((obs) => (
                      <tr key={obs.id}>
                        <td className="mono tabular text-text-secondary">
                          {formatDateTime(obs.observed_at)}
                        </td>
                        <td>
                          <SourceBadge source={obs.source} />
                        </td>
                        <td>
                          <PriceTypeBadge priceType={obs.price_type} />
                        </td>
                        <td className="mono tabular text-right text-text-primary">
                          {formatJpy(obs.price_jpy)}
                        </td>
                        <td className="text-text-secondary">{obs.condition_label ?? "—"}</td>
                        <td>
                          <StockStatusBadge status={obs.stock_status} />
                        </td>
                        <td className="mono tabular text-right text-text-secondary">
                          {obs.listing_count ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}


interface QuickAddWishlistFormState {
  priority: WishlistPriority;
  target_buy_price_jpy: string;
  preferred_condition: string;
  preferred_source: string;
}

const EMPTY_QUICK_ADD_WISHLIST_FORM: QuickAddWishlistFormState = {
  priority: "medium",
  target_buy_price_jpy: "",
  preferred_condition: "",
  preferred_source: "",
};

function QuickAddWishlistForm({ cardId, onAdded }: { cardId: number; onAdded: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<QuickAddWishlistFormState>(EMPTY_QUICK_ADD_WISHLIST_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function updateField<K extends keyof QuickAddWishlistFormState>(
    key: K,
    value: QuickAddWishlistFormState[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    let targetBuy: number | null = null;
    if (form.target_buy_price_jpy !== "") {
      targetBuy = Number(form.target_buy_price_jpy);
      if (Number.isNaN(targetBuy) || targetBuy < 0) {
        setFormError("Target buy price must be 0 or greater.");
        return;
      }
    }

    setSaving(true);
    try {
      await createWishlistItem({
        card_id: cardId,
        priority: form.priority,
        target_buy_price_jpy: targetBuy,
        preferred_condition: form.preferred_condition || null,
        preferred_source: form.preferred_source || null,
      });
      setForm(EMPTY_QUICK_ADD_WISHLIST_FORM);
      setExpanded(false);
      onAdded();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to add this card to your wishlist.");
    } finally {
      setSaving(false);
    }
  }

  if (!expanded) {
    return (
      <ActionButton variant="primary" onClick={() => setExpanded(true)}>
        + Add to wishlist
      </ActionButton>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {formError && (
        <div className="rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {formError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormField label="Priority">
          <select
            value={form.priority}
            onChange={(e) => updateField("priority", e.target.value as WishlistPriority)}
            className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
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
            className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary"
          />
        </FormField>

        <FormField label="Preferred condition">
          <input
            type="text"
            value={form.preferred_condition}
            onChange={(e) => updateField("preferred_condition", e.target.value)}
            placeholder="raw, PSA 10, …"
            className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
          />
        </FormField>

        <FormField label="Preferred source">
          <input
            type="text"
            value={form.preferred_source}
            onChange={(e) => updateField("preferred_source", e.target.value)}
            placeholder="yuyutei, snkrdunk, …"
            className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
          />
        </FormField>
      </div>

      <div className="flex gap-2">
        <ActionButton variant="primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Add to wishlist"}
        </ActionButton>
        <button
          type="button"
          onClick={() => {
            setExpanded(false);
            setForm(EMPTY_QUICK_ADD_WISHLIST_FORM);
            setFormError(null);
          }}
          disabled={saving}
          className="rounded border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

interface QuickAddFormState {
  quantity: string;
  condition_label: string;
  purchase_price_jpy: string;
  purchase_date: string;
  purchase_source: string;
  target_sell_price_jpy: string;
  status: string;
  notes: string;
}

const EMPTY_QUICK_ADD_FORM: QuickAddFormState = {
  quantity: "1",
  condition_label: "raw",
  purchase_price_jpy: "",
  purchase_date: "",
  purchase_source: "",
  target_sell_price_jpy: "",
  status: "hold",
  notes: "",
};

function QuickAddForm({
  cardId,
  onAdded,
}: {
  cardId: number;
  onAdded: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<QuickAddFormState>(EMPTY_QUICK_ADD_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function updateField<K extends keyof QuickAddFormState>(
    key: K,
    value: QuickAddFormState[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function validateForm(): CollectionItemInput | null {
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

    if (!(COLLECTION_STATUS_OPTIONS as readonly string[]).includes(form.status)) {
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const body = validateForm();
    if (!body) return;

    setSaving(true);
    try {
      await createCollectionItem(body);
      setForm(EMPTY_QUICK_ADD_FORM);
      setExpanded(false);
      onAdded();
    } catch {
      setFormError("Failed to add this card to your collection.");
    } finally {
      setSaving(false);
    }
  }

  if (!expanded) {
    return (
      <ActionButton variant="primary" onClick={() => setExpanded(true)}>
        + Add to collection
      </ActionButton>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {formError && (
        <div className="rounded border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {formError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
            onChange={(e) => updateField("condition_label", e.target.value)}
            placeholder="raw, PSA 10, …"
            className="w-full rounded border border-border-default bg-bg-page px-2 py-1 text-sm text-text-primary placeholder:text-text-faint"
          />
        </FormField>

        <FormField label="Purchase price (JPY)">
          <input
            type="number"
            min={0}
            value={form.purchase_price_jpy}
            onChange={(e) => updateField("purchase_price_jpy", e.target.value)}
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
            onChange={(e) => updateField("purchase_source", e.target.value)}
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
            {COLLECTION_STATUS_OPTIONS.map((s) => (
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
          {saving ? "Saving…" : "Add to collection"}
        </ActionButton>
        <button
          type="button"
          onClick={() => {
            setExpanded(false);
            setForm(EMPTY_QUICK_ADD_FORM);
            setFormError(null);
          }}
          disabled={saving}
          className="rounded border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

const META_FIELDS: { key: keyof Card; label: string }[] = [
  { key: "cost", label: "Cost" },
  { key: "power", label: "Power" },
  { key: "counter", label: "Counter" },
  { key: "attribute", label: "Attribute" },
  { key: "color", label: "Color" },
  { key: "card_type", label: "Type" },
  { key: "artist", label: "Artist" },
  { key: "character", label: "Character" },
];

/** Market Index as the card's primary collector-facing value (design brief
 * Phase 9), placed inside the hero panel right after identity - loading and
 * error states are quiet/inline (a whole-panel LoadingState/ErrorState here
 * would compete with the image for attention on first paint). The staging
 * note is restrained (small, muted text) since SCRAPING_MODE stays "mock"
 * for this task - never claims these are live market prices. */
function MarketIndexSection({
  status,
  index,
}: {
  status: Status;
  index: MarketIndex | null;
}) {
  if (status === "loading") {
    return <div className="h-12 w-40 animate-pulse rounded-control bg-bg-elevated" />;
  }
  if (status === "error" || !index) {
    return <p className="text-xs text-text-muted">Market Index unavailable right now.</p>;
  }
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-text-secondary">
        Market Index
      </div>
      <MarketIndexValue index={index} size="lg" />
      <p className="mt-1 text-[10px] text-text-faint">
        Staging data - prices are from the mock price source (SCRAPING_MODE=mock), not live.
      </p>
    </div>
  );
}

/** Compact metadata grid (cost/power/counter/attribute/color/type/artist/
 * character/release date) - only rendered fields the card actually has
 * (catalog enrichment is sparse; most existing rows have none of this),
 * never a "not available" wall for a field that's simply not part of this
 * card's data at all. */
function CardMetadataGrid({ card }: { card: Card }) {
  const present = META_FIELDS.filter(({ key }) => card[key] !== null && card[key] !== undefined);
  if (present.length === 0 && !card.release_date) return null;

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      {present.map(({ key, label }) => (
        <div key={key}>
          <dt className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</dt>
          <dd className="text-text-primary">{String(card[key])}</dd>
        </div>
      ))}
      {card.release_date && (
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-text-secondary">Release date</dt>
          <dd className="text-text-primary">{formatDate(card.release_date)}</dd>
        </div>
      )}
    </dl>
  );
}

/** Effect/trigger text - only rendered when at least one is present. */
function CardEffectText({ card }: { card: Card }) {
  if (!card.effect_text && !card.trigger_text) return null;

  return (
    <div className="space-y-2 text-sm">
      {card.effect_text && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-secondary">Effect</div>
          <p className="whitespace-pre-line text-text-primary">{card.effect_text}</p>
        </div>
      )}
      {card.trigger_text && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-text-secondary">Trigger</div>
          <p className="whitespace-pre-line text-text-primary">{card.trigger_text}</p>
        </div>
      )}
    </div>
  );
}

/** Admin-only source-mappings mini panel - compact, clearly admin-styled,
 * only ever rendered for a role="admin" session (see isAdmin in the page
 * component). Uses the existing GET /admin/source-mappings?card_code= list
 * (server-side-authorized via the Next.js proxy - see
 * src/lib/adminProxy.ts), not the /quality review endpoint. */
function AdminSourceMappingsMiniPanel({ mappings }: { mappings: SourceCardMapping[] }) {
  return (
    <div className="admin-preview rounded-panel p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">Source mappings (admin)</h2>
        <div className="flex flex-wrap gap-3 text-xs">
          <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:text-sky-300">
            Source Mapping Quality →
          </Link>
          <Link href="/admin/card-audit" className="text-sky-400 hover:text-sky-300">
            Card Audit →
          </Link>
        </div>
      </div>

      {mappings.length === 0 ? (
        <EmptyState variant="inline">No source mappings for this card.</EmptyState>
      ) : (
        <div className="space-y-1.5">
          {mappings.map((m) => (
            <div
              key={m.id}
              className="flex flex-wrap items-center gap-2 rounded-control border border-border-default bg-bg-page px-2 py-1.5 text-xs"
            >
              <SourceBadge source={m.source_name ?? "unknown"} />
              <span className="text-text-secondary">{m.is_active ? "active" : "inactive"}</span>
              <span className="text-text-secondary">
                {m.manual_verified ? "verified" : "unverified"}
              </span>
              {m.match_confidence_label && (
                <span className="text-text-muted">{m.match_confidence_label}</span>
              )}
              {m.source_url && (
                <a
                  href={m.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-sky-400 hover:underline"
                >
                  source link
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
