"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionItemTagsCell } from "@/components/CollectionItemTagsCell";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { FormField } from "@/components/FormField";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { PriceChart } from "@/components/PriceChart";
import { PriceTypeBadge } from "@/components/PriceTypeBadge";
import { RarityBadge } from "@/components/RarityBadge";
import { SourceBadge } from "@/components/SourceBadge";
import { StockStatusBadge } from "@/components/StockStatusBadge";
import { WishlistPriorityBadge } from "@/components/WishlistPriorityBadge";
import { WishlistStatusBadge } from "@/components/WishlistStatusBadge";
import {
  COLLECTION_STATUS_OPTIONS,
  WISHLIST_PRIORITIES,
  type Card,
  type CollectionItem,
  type CollectionItemInput,
  type CollectorTag,
  type PriceObservation,
  type WishlistItem,
  type WishlistPriority,
  assignCardTag,
  createCollectionItem,
  createWishlistItem,
  fetchCard,
  fetchCardPrices,
  fetchCollectionItems,
  fetchCollectorTags,
  fetchWishlistItems,
  unassignCardTag,
} from "@/lib/api";
import { cardDisplayName, formatDateTime, formatJpy, formatSignedJpy } from "@/lib/format";

type Status = "loading" | "error" | "ready";

interface KeyPriceLine {
  label: string;
  source: string;
  priceType: string;
}

const KEY_PRICE_LINES: KeyPriceLine[] = [
  { label: "Yuyu-Tei sell", source: "yuyutei", priceType: "sell" },
  { label: "Yuyu-Tei buy", source: "yuyutei", priceType: "buy" },
  { label: "SNKRDUNK floor", source: "snkrdunk", priceType: "floor" },
];

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
        <Link
          href="/dashboard"
          className="mb-4 inline-block text-sm text-neutral-400 hover:text-neutral-100"
        >
          ← Back to dashboard
        </Link>

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading card…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load this card from the API.
          </div>
        )}

        {status === "ready" && card && (
          <div className="space-y-6">
            <div className="flex flex-col gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4 sm:flex-row">
              {card.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={card.image_url}
                  alt={cardDisplayName(card)}
                  className="h-48 w-36 rounded-md border border-neutral-800 object-cover"
                />
              )}
              <div className="flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold text-neutral-100">
                    {cardDisplayName(card)}
                  </h1>
                  <RarityBadge rarity={card.rarity} />
                </div>
                {card.name_en && card.name_jp && (
                  <p className="text-sm text-neutral-500">{card.name_jp}</p>
                )}
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 pt-2 text-sm sm:grid-cols-4">
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Code
                    </dt>
                    <dd className="font-mono text-neutral-200">
                      {card.card_code}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">Set</dt>
                    <dd className="text-neutral-200">{card.set_code}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Variant
                    </dt>
                    <dd className="text-neutral-200">
                      {card.variant ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Language
                    </dt>
                    <dd className="uppercase text-neutral-200">
                      {card.language}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>

            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <h2 className="mb-2 text-sm font-semibold text-neutral-100">Card tags</h2>
              {tagError && (
                <div className="mb-2 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
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

            <CollectionSection
              cardId={card.id}
              status={collectionStatus}
              items={collectionItems}
              onChanged={refreshCollectionItems}
            />

            <WishlistSection
              cardId={card.id}
              status={wishlistStatus}
              items={wishlistItems}
              onChanged={() => refreshWishlistItems(card.card_code)}
            />

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {KEY_PRICE_LINES.map((line) => {
                const observation = latestFor(prices, line.source, line.priceType);
                return (
                  <div
                    key={line.label}
                    className="rounded-lg border border-neutral-800 bg-neutral-900 p-3"
                  >
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <SourceBadge source={line.source} />
                      <PriceTypeBadge priceType={line.priceType} />
                    </div>
                    <div className="text-lg font-semibold text-neutral-100">
                      {observation ? formatJpy(observation.price_jpy) : "—"}
                    </div>
                    <div className="text-xs text-neutral-500">
                      {observation
                        ? formatDateTime(observation.observed_at)
                        : "No observations yet"}
                    </div>
                  </div>
                );
              })}
            </div>

            <div>
              <h2 className="mb-2 text-sm font-semibold text-neutral-100">
                Price history
              </h2>
              <PriceChart observations={prices} />
            </div>

            <div>
              <h2 className="mb-2 text-sm font-semibold text-neutral-100">
                Price observations
              </h2>
              {latestFirst.length === 0 ? (
                <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                  No price observations yet.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-neutral-800">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                        <th className="px-3 py-2 font-medium">Observed at</th>
                        <th className="px-3 py-2 font-medium">Source</th>
                        <th className="px-3 py-2 font-medium">Type</th>
                        <th className="px-3 py-2 font-medium text-right">
                          Price
                        </th>
                        <th className="px-3 py-2 font-medium">Condition</th>
                        <th className="px-3 py-2 font-medium">Stock</th>
                        <th className="px-3 py-2 font-medium text-right">
                          Listings
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {latestFirst.map((obs) => (
                        <tr
                          key={obs.id}
                          className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                        >
                          <td className="px-3 py-2 text-neutral-300">
                            {formatDateTime(obs.observed_at)}
                          </td>
                          <td className="px-3 py-2">
                            <SourceBadge source={obs.source} />
                          </td>
                          <td className="px-3 py-2">
                            <PriceTypeBadge priceType={obs.price_type} />
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-200">
                            {formatJpy(obs.price_jpy)}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {obs.condition_label ?? "—"}
                          </td>
                          <td className="px-3 py-2">
                            <StockStatusBadge status={obs.stock_status} />
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-400">
                            {obs.listing_count ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function CollectionSection({
  cardId,
  status,
  items,
  onChanged,
}: {
  cardId: number;
  status: Status;
  items: CollectionItem[];
  onChanged: () => void;
}) {
  const totalQuantity = items.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-neutral-100">Collection</h2>
        <Link
          href="/collection"
          className="text-xs text-sky-400 hover:text-sky-300"
        >
          View collection →
        </Link>
      </div>

      {status === "loading" && (
        <p className="text-sm text-neutral-500">Loading collection status…</p>
      )}

      {status === "error" && (
        <p className="text-sm text-rose-300">
          Failed to load collection status.
        </p>
      )}

      {status === "ready" && items.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-neutral-300">
            You own{" "}
            <span className="font-semibold text-neutral-100">
              {totalQuantity}
            </span>{" "}
            cop{totalQuantity === 1 ? "y" : "ies"}.
          </p>
          <div className="divide-y divide-neutral-800 rounded border border-neutral-800">
            {items.map((item) => (
              <div key={item.id} className="space-y-1.5 px-3 py-2">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span className="font-medium text-neutral-200">
                    {item.quantity}×
                  </span>
                  <span className="text-neutral-400">
                    {item.condition_label ?? "raw"}
                  </span>
                  <span className="text-neutral-200">
                    {formatJpy(item.purchase_price_jpy)}
                  </span>
                  <CollectionStatusBadge status={item.status} />
                  {item.latest_grading_status && (
                    <GradingStatusBadge status={item.latest_grading_status} />
                  )}
                  <Link
                    href={`/grading?item_id=${item.id}`}
                    className="text-xs font-medium text-violet-400 hover:text-violet-300"
                  >
                    Create grading submission
                  </Link>
                </div>
                {item.grading_submissions.length > 0 && (
                  <div className="flex flex-wrap gap-2 text-xs text-neutral-500">
                    {item.grading_submissions.map((s) => (
                      <span
                        key={s.id}
                        className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1"
                      >
                        {s.grading_company} · {s.submission_status.replace(/_/g, " ")}
                        {s.final_grade ? ` · grade ${s.final_grade}` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {status === "ready" && items.length === 0 && (
        <QuickAddForm cardId={cardId} onAdded={onChanged} />
      )}
    </div>
  );
}

function WishlistSection({
  cardId,
  status,
  items,
  onChanged,
}: {
  cardId: number;
  status: Status;
  items: WishlistItem[];
  onChanged: () => void;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-neutral-100">Wishlist</h2>
        <Link href="/wishlist" className="text-xs text-sky-400 hover:text-sky-300">
          View wishlist →
        </Link>
      </div>

      {status === "loading" && <p className="text-sm text-neutral-500">Loading wishlist status…</p>}

      {status === "error" && <p className="text-sm text-rose-300">Failed to load wishlist status.</p>}

      {status === "ready" && items.length > 0 && (
        <div className="mb-3 divide-y divide-neutral-800 rounded border border-neutral-800">
          {items.map((item) => (
            <div key={item.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <WishlistPriorityBadge priority={item.priority} />
              <WishlistStatusBadge status={item.status} />
              <span className="text-neutral-400">
                Target: {item.target_buy_price_jpy !== null ? formatJpy(item.target_buy_price_jpy) : "not set"}
              </span>
              {item.target_hit && (
                <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-500/30">
                  target hit
                </span>
              )}
              {item.gap_to_target_jpy !== null && (
                <span className="text-xs text-neutral-500">
                  gap {formatSignedJpy(item.gap_to_target_jpy)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {status === "ready" && items.length === 0 && (
        <p className="mb-3 text-sm text-neutral-500">Not on your wishlist yet.</p>
      )}

      {status === "ready" && <QuickAddWishlistForm cardId={cardId} onAdded={onChanged} />}
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
      <button
        onClick={() => setExpanded(true)}
        className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white"
      >
        + Add to wishlist
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {formError && (
        <div className="rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {formError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
            placeholder="yuyutei, snkrdunk, …"
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
          />
        </FormField>
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Add to wishlist"}
        </button>
        <button
          type="button"
          onClick={() => {
            setExpanded(false);
            setForm(EMPTY_QUICK_ADD_WISHLIST_FORM);
            setFormError(null);
          }}
          disabled={saving}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
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
      <button
        onClick={() => setExpanded(true)}
        className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white"
      >
        + Add to collection
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {formError && (
        <div className="rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
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
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
          />
        </FormField>

        <FormField label="Condition">
          <input
            type="text"
            value={form.condition_label}
            onChange={(e) => updateField("condition_label", e.target.value)}
            placeholder="raw, PSA 10, …"
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
          />
        </FormField>

        <FormField label="Purchase price (JPY)">
          <input
            type="number"
            min={0}
            value={form.purchase_price_jpy}
            onChange={(e) => updateField("purchase_price_jpy", e.target.value)}
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
            onChange={(e) => updateField("purchase_source", e.target.value)}
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
          {saving ? "Saving…" : "Add to collection"}
        </button>
        <button
          type="button"
          onClick={() => {
            setExpanded(false);
            setForm(EMPTY_QUICK_ADD_FORM);
            setFormError(null);
          }}
          disabled={saving}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
