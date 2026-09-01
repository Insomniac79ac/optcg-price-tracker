"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionItemTagsCell } from "@/components/CollectionItemTagsCell";
import { FormField } from "@/components/FormField";
import { SourceBadge } from "@/components/SourceBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { CardActivityPanel } from "@/components/ui/CardActivityPanel";
import { CardIdentityBlock } from "@/components/ui/CardIdentityBlock";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import {
  CardPrintingChooser,
  type PrintingChooserStatus,
} from "@/components/ui/CardPrintingChooser";
import { GradingSummaryPanel } from "@/components/ui/GradingSummaryPanel";
import { OwnershipSummaryPanel } from "@/components/ui/OwnershipSummaryPanel";
import { WishlistSummaryPanel } from "@/components/ui/WishlistSummaryPanel";
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
  type SourceCardMapping,
  type ValuationMode,
  type WishlistItem,
  type WishlistPriority,
  assignCardTag,
  createCollectionItem,
  createWishlistItem,
  fetchAdminSourceMappings,
  fetchCard,
  fetchCollectionItems,
  fetchCollectionValuation,
  fetchCollectorActivity,
  fetchCollectorNotes,
  fetchCollectorTags,
  fetchWishlistItems,
  unassignCardTag,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  fetchPrintCatalogue,
  resolveCanonicalPrintIdentity,
  toPrintUiModel,
  type CanonicalPrintIdentity,
  type PrintUiModel,
} from "@/lib/prints";

type Status = "loading" | "error" | "ready";

export default function CardDetailPage() {
  const params = useParams<{ id: string }>();
  const cardId = params.id;

  /** Whether there is a real signed-in collector.
   *
   * /cards/:id is public collector surface (see lib/proxyGuard.ts), so this
   * component now renders for anonymous visitors. Every user-specific fetch
   * below is gated on this: not for authorization - each of those endpoints
   * answers 401 without a bearer token on its own - but because firing six
   * requests that can only 401 would be pure noise, and because an empty
   * result from a failed request is indistinguishable from "you own none of
   * these", which would be a lie told to a signed-out reader.
   *
   * "authenticated" specifically, never `Boolean(session)`: during the
   * "loading" phase there is no token to send yet, and a request made then
   * would 401 exactly like an anonymous one. */
  const { data: session, status: sessionStatus } = useSession();
  const isSignedIn = sessionStatus === "authenticated";
  const isAdmin = session?.user?.role === "admin";

  const [card, setCard] = useState<Card | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const [prints, setPrints] = useState<PrintUiModel[]>([]);
  const [canonicalIdentity, setCanonicalIdentity] =
    useState<CanonicalPrintIdentity | null>(null);
  const [printsStatus, setPrintsStatus] = useState<PrintingChooserStatus>("loading");

  const [collectionItems, setCollectionItems] = useState<CollectionItem[]>([]);
  const [collectionStatus, setCollectionStatus] = useState<Status>("loading");

  const [wishlistItems, setWishlistItems] = useState<WishlistItem[]>([]);
  const [wishlistStatus, setWishlistStatus] = useState<Status>("loading");

  const [allTags, setAllTags] = useState<CollectorTag[]>([]);
  const [tagError, setTagError] = useState<string | null>(null);

  /** This card's printings, from the public print catalogue.
   *
   * WHY BY CARD CODE. `/cards/{id}` is a LEGACY `cards` row, and
   * `card_prints.canonical_card_id` points at `canonical_cards`, not at that
   * table - joining the two is the known way to get silent garbage (see
   * lib/prints.ts). The API exposes no legacy-id -> canonical-id link and
   * `/prints` takes no canonical_card_id filter, so the card's own published
   * `card_code` is the identifier both sides genuinely share.
   *
   * `q` is a substring ILIKE over canonical name_en/name_jp/card_code, so the
   * exact-code filter below is not decoration: it is what turns a search
   * result into an identity match, and it is the only thing keeping another
   * card's printing off this page. `card_code` is unique across
   * `canonical_cards`, so an exact match resolves to exactly one card.
   *
   * One request, no pagination: the largest card in the corpus has 9 active
   * printings against a limit of 100.
   */
  useEffect(() => {
    if (!card?.card_code) return;
    const cardCode = card.card_code;
    let cancelled = false;
    setPrintsStatus("loading");
    setCanonicalIdentity(null);

    fetchPrintCatalogue({ q: cardCode, limit: 100 })
      .then((result) => {
        if (cancelled) return;
        // PRINT_CATALOGUE_EXACT_CODE_NOTE: `q` is a substring search, so this
        // exact-code filter is what turns a search result into an identity
        // match. Everything below - the printings AND the name this page
        // shows - is derived from these records only.
        const exact = result.items.filter((item) => item.card_code === cardCode);
        setPrints(exact.map(toPrintUiModel));
        setCanonicalIdentity(resolveCanonicalPrintIdentity(exact));
        setPrintsStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setPrints([]);
        setCanonicalIdentity(null);
        setPrintsStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [card?.card_code]);

  useEffect(() => {
    let cancelled = false;

    fetchCard(cardId)
      .then((cardData) => {
        if (cancelled) return;
        setCard(cardData);
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
    if (!isSignedIn) return;
    fetchCollectorTags()
      .then(setAllTags)
      .catch(() => setAllTags([]));
  }, [isSignedIn]);

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
    if (!isSignedIn) return;
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
  }, [cardId, isSignedIn]);

  function refreshWishlistItems(cardCode: string) {
    if (!isSignedIn) return;
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
  }, [card?.card_code, isSignedIn]);

  // Ownership valuation (cost basis/current value/P&L) - same source
  // /collection itself uses, so the numbers never disagree.
  const [valuationMode] = useState<ValuationMode>("raw_market");
  const [valuationItems, setValuationItems] = useState<PortfolioValuationItem[]>([]);

  useEffect(() => {
    if (!isSignedIn) return;
    fetchCollectionValuation(valuationMode)
      .then((data) => setValuationItems(data.items.filter((i) => i.card_id === Number(cardId))))
      .catch(() => setValuationItems([]));
  }, [cardId, valuationMode, isSignedIn]);

  // Notes/activity for this card.
  const [notes, setNotes] = useState<CollectorNote[]>([]);
  const [activity, setActivity] = useState<CollectorActivityEvent[]>([]);

  function refreshNotes() {
    if (!isSignedIn) return;
    fetchCollectorNotes({ card_id: Number(cardId) })
      .then((data) => setNotes(data.items))
      .catch(() => setNotes([]));
  }

  useEffect(() => {
    if (!isSignedIn) return;
    refreshNotes();
    fetchCollectorActivity({ card_id: Number(cardId) })
      .then((data) => setActivity(data.events))
      .catch(() => setActivity([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId, isSignedIn]);

  // Admin-only source mappings mini panel - only fetched (and only ever
  // shown) for a role="admin" session, same gate as every other admin-only
  // UI element in this app (see src/lib/adminSession.ts). Unchanged by the
  // route becoming public: an anonymous visitor is not an admin.
  const [adminMappings, setAdminMappings] = useState<SourceCardMapping[]>([]);

  useEffect(() => {
    if (!isAdmin || !card) return;
    fetchAdminSourceMappings({ card_code: card.card_code })
      .then((data) => setAdminMappings(data.items))
      .catch(() => setAdminMappings([]));
  }, [isAdmin, card?.card_code]);

  const gradingSubmissions = collectionItems.flatMap((item) => item.grading_submissions);

  /** The only name this page may show for the card.
   *
   * The legacy `cards` row is NOT the authority: 10 of 25 staging rows carry a
   * `card_code` whose canonical card is a different character, so rendering
   * `card.name_en` here would label a set of Roronoa Zoro printings "Monkey D.
   * Luffy". Identity therefore comes from the canonical print records for this
   * exact code, and falls back to the code alone - never to the legacy name -
   * whenever those records are missing, still loading, or disagree with one
   * another. The code is the one thing both sides agree on. */
  const displayIdentity = canonicalIdentity?.name ?? card?.card_code ?? "";

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
          <ErrorState tone="collector">This card couldn’t be loaded right now.</ErrorState>
        )}

        {status === "ready" && card && (
          // flex + explicit order (not space-y) so mobile can prioritize the
          // price panel above ownership/wishlist/grading while desktop keeps
          // the original document order (see design brief "Card detail" -
          // mobile: image/identity, then price source, then ownership panels;
          // admin panel stays lowest-priority on every breakpoint).
          <div className="flex flex-col gap-6">
            {/* 1. Hero - image + identity + compact metadata grid + effect/trigger text.
                NO rarity and NO variant: this page now stands for a FAMILY of
                printings, and those printings differ in exactly those two
                dimensions (OP04-044 spans Super Rare base, Alt Art, Reprint
                and an SP Card). A single legacy chip up here would describe
                one of them at most, and would contradict the tiles below - so
                rarity and variant are stated per printing, on the printing,
                and nowhere else. Nothing is elected to represent the set. */}
            <div className="panel flex flex-col gap-4 p-4 sm:flex-row">
              <CardImageFrame
                imageUrl={card.image_url}
                alt={displayIdentity}
                cardCode={card.card_code}
                setCode={card.set_code}
                size="lg"
              />
              <div className="flex-1 space-y-3">
                <CardIdentityBlock
                  cardCode={card.card_code}
                  name={displayIdentity}
                  // The legacy Japanese name is suppressed for the same reason
                  // the English one is: it is the same untrusted row.
                  nameSecondary={null}
                  language={card.language}
                  setCode={card.set_code}
                  asHeading
                />
                <CardMetadataGrid card={card} />
                <CardEffectText card={card} />
              </div>
            </div>

            {/* The page's purpose: pick the exact printing. Shares order-1
                with the price panel below and precedes it in the DOM, so on
                mobile a collector reaches the printings before any card-level
                price - which is card-level precisely because it cannot know
                which printing they meant. */}
            <div className="order-1 lg:order-none">
              <CardPrintingChooser
                status={printsStatus}
                prints={prints}
                cardCode={card.card_code}
                canonicalName={canonicalIdentity?.name ?? null}
              />
            </div>

            {isSignedIn && (
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
            )}

            {/* 2. Ownership / wishlist / grading - the signed-in collector's own
                relationship to this card. Rendered only for a real session:
                these panels' own empty states ("Not in collection yet.") are
                statements ABOUT THE READER, and showing them to a signed-out
                visitor would assert something this page cannot know. The
                header's Sign in is the affordance; nothing is duplicated here. */}
            {isSignedIn && (
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
            )}

            {/* 5. Notes/activity - the reader's own notes and their own event
                history, so same rule as the panels above. */}
            {isSignedIn && (
            <div className="order-5 lg:order-none">
              <CardActivityPanel
                cardId={card.id}
                notes={notes}
                activity={activity}
                onNoteAdded={refreshNotes}
              />
            </div>
            )}

            {/* 6. Admin mini-panel - only rendered for admin-token holders;
                lowest-priority panel on mobile (design brief - "admin mini
                panel should be collapsed or lower priority"). */}
            {isAdmin && (
              <div className="order-6 lg:order-none">
                <AdminSourceMappingsMiniPanel mappings={adminMappings} />
              </div>
            )}

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
 * note is restrained (small, muted text) and never claims these are live
 * market prices - it says so in collector language rather than naming the
 * backend's own scraping-mode flag, which is an implementation detail no
 * visitor can act on. */
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
