"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton, type ActionButtonVariant } from "@/components/ui/ActionButton";
import { AdminActionPanel } from "@/components/ui/AdminActionPanel";
import { Badge } from "@/components/ui/Badge";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";
import { ConfirmActionModal } from "@/components/ui/ConfirmActionModal";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS, FilterBar } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { QuickActionBar } from "@/components/ui/QuickActionBar";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type BulkMappingAction,
  type BulkMappingUpdateResponse,
  type Card,
  type CompatibilityCardUpdateResult,
  type MappingQualityItem,
  type MappingQualitySummary,
  type RecheckQualityResult,
  type SuggestedCardsForMapping,
  bulkUpdateMappings,
  fetchCards,
  fetchMappingQuality,
  fetchSuggestedCardsForMapping,
  recheckMappingQuality,
  updateMappingCompatibilityCard,
} from "@/lib/api";
import { cardDisplayName, formatDateTime } from "@/lib/format";

const RISK_FILTERS = [
  { value: "", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "review", label: "Review" },
  { value: "ok", label: "OK" },
];

const REVIEW_STATUS_OPTIONS = ["", "approved", "needs_review", "rejected"];
const CONFIDENCE_LABEL_OPTIONS = ["", "exact", "high", "medium", "low", "very_low", "unknown"];
const ISSUE_TYPE_OPTIONS = [
  "",
  "low_confidence",
  "card_code_mismatch",
  "set_code_mismatch",
  "variant_mismatch",
  "treatment_mismatch",
  "duplicate_source_url",
  "inactive_with_recent_price",
  "active_without_recent_price",
  "stale_mapping",
  "unverified_mapping",
  "missing_source_url",
  "missing_card_reference",
  "legacy_compatibility_mapping",
  "broken_mapping_identity",
];

const RISK_STYLES: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  review: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  warning: "bg-amber-500/15 text-signal-warning ring-amber-500/30",
  critical: "bg-rose-500/15 text-signal-red ring-rose-500/30",
};

const LIMIT_OPTIONS = [50, 100, 200, 500] as const;

const DESTRUCTIVE_ACTIONS: BulkMappingAction[] = ["reject", "deactivate"];

const BULK_ACTIONS: { action: BulkMappingAction; label: string; variant: ActionButtonVariant }[] = [
  { action: "approve", label: "Approve", variant: "default" },
  { action: "reject", label: "Reject", variant: "danger" },
  { action: "deactivate", label: "Deactivate", variant: "danger" },
  { action: "activate", label: "Activate", variant: "default" },
  { action: "mark_verified", label: "Mark verified", variant: "default" },
  { action: "mark_pending", label: "Mark pending", variant: "default" },
];

function destructiveLabel(action: BulkMappingAction): string {
  return action === "reject" ? "Reject" : "Deactivate";
}

/** Mapping risk has its own ok/review/warning/critical vocabulary (distinct
 * from the app-wide low/medium/high/critical RiskBadge) - it's also the
 * exact vocabulary the RISK_FILTERS segmented buttons above already use, so
 * keeping this page's own labels/colors (on the shared Badge shell) avoids
 * a mismatch between the filter buttons and the badges they filter by. */
function RiskBadge({ level }: { level: string }) {
  const style = RISK_STYLES[level] ?? "bg-neutral-500/15 text-text-secondary ring-neutral-500/30";
  return <Badge label={level} className={`ring-1 ring-inset ${style}`} />;
}

const IDENTITY_STYLES = {
  exact: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  legacy_compatibility: "bg-amber-500/15 text-signal-warning ring-amber-500/30",
  broken: "bg-rose-500/15 text-signal-red ring-rose-500/30",
} as const;

function IdentityClassification({ item }: { item: MappingQualityItem }) {
  const content = {
    exact: {
      label: "Exact print",
      description: "Authoritative physical-print mapping",
    },
    legacy_compatibility: {
      label: "Legacy compatibility",
      description: "Compatibility-only; not modern exact pricing lineage",
    },
    broken: {
      label: "Broken",
      description: "Structural review required",
    },
  }[item.identity_classification];

  return (
    <div className="min-w-[10rem] space-y-1">
      <Badge
        label={content.label}
        className={`ring-1 ring-inset ${IDENTITY_STYLES[item.identity_classification]}`}
      />
      <div className="text-[11px] leading-4 text-text-muted">{content.description}</div>
    </div>
  );
}

function AuthoritativePrintIdentity({ item }: { item: MappingQualityItem }) {
  if (item.identity_classification !== "exact" || item.card_print_id === null) {
    return (
      <div className="min-w-[12rem] text-xs text-text-muted">
        {item.identity_classification === "legacy_compatibility"
          ? "No authoritative CardPrint — legacy compatibility only"
          : "Authoritative print unavailable — structural review required"}
      </div>
    );
  }

  const product = [item.release_product_code, item.release_product_name].filter(Boolean).join(" — ");
  const variant = [item.official_asset_variant, item.treatment, item.official_rarity]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="min-w-[13rem] space-y-0.5 text-xs">
      <Link href={`/prints/${item.card_print_id}`} className="mono font-semibold text-sky-400 hover:underline">
        CardPrint #{item.card_print_id}
      </Link>
      <div className="text-text-primary">
        {item.canonical_card_code ?? "Unknown code"}
        {item.canonical_name_en ? ` — ${item.canonical_name_en}` : ""}
      </div>
      {product && <div className="text-text-secondary">{product}</div>}
      <div className="text-text-muted">
        {[item.print_language, variant].filter(Boolean).join(" · ") || "No additional print metadata"}
      </div>
    </div>
  );
}

function CompatibilityCardIdentity({ item }: { item: MappingQualityItem }) {
  const compatibilityCardId = item.compatibility_card_id;
  return (
    <div className="min-w-[12rem] space-y-0.5 text-xs">
      <div className="text-text-primary">
        Compatibility card:{" "}
        {compatibilityCardId === null ? (
          <span className="font-medium">None</span>
        ) : (
          <Link href={`/cards/${compatibilityCardId}`} className="mono text-sky-400 hover:underline">
            {item.card_code ?? `#${compatibilityCardId}`}
          </Link>
        )}
      </div>
      <div className="text-text-muted">Status: {item.compatibility_card_status.replaceAll("_", " ")}</div>
      {item.compatibility_issue_types.length > 0 && (
        <div className="text-signal-warning">{item.compatibility_issue_types.join(", ")}</div>
      )}
      {compatibilityCardId === null && item.identity_classification === "exact" && (
        <div className="text-emerald-400">Optional metadata; exact pricing identity is valid.</div>
      )}
    </div>
  );
}

function MappingConfidence({ item }: { item: MappingQualityItem }) {
  if (item.confidence_scope === "structural_failure") {
    return <div className="min-w-[11rem] text-xs text-signal-red">Structural failure — no confidence score</div>;
  }

  const compatibilityOnly = item.confidence_scope === "compatibility_only";
  const score = compatibilityOnly ? item.compatibility_match_confidence : item.match_confidence;
  const label = compatibilityOnly
    ? item.compatibility_match_confidence_label
    : item.match_confidence_label;

  return (
    <div className="min-w-[12rem] space-y-1 text-xs">
      <div className={compatibilityOnly ? "text-signal-warning" : "text-text-primary"}>
        {compatibilityOnly ? "Compatibility-only confidence" : "Exact-print confidence"}
      </div>
      <div className="flex items-center gap-2">
        <span className="mono tabular text-text-secondary">{score ?? "—"}</span>
        <ConfidenceBadge level={label ?? "unknown"} />
      </div>
      {!compatibilityOnly && Object.keys(item.exact_confidence_dimensions).length > 0 && (
        <div className="flex max-w-[16rem] flex-wrap gap-1 text-[10px] text-text-muted">
          {Object.entries(item.exact_confidence_dimensions).map(([dimension, value]) => (
            <span key={dimension} className="rounded-control bg-bg-elevated px-1.5 py-0.5">
              {dimension.replaceAll("_", " ")}: {value.status.replaceAll("_", " ")}
            </span>
          ))}
        </div>
      )}
      {compatibilityOnly && item.compatibility_issue_types.length > 0 && (
        <div className="text-text-muted">{item.compatibility_issue_types.join(", ")}</div>
      )}
    </div>
  );
}

function idLabel(id: number | null): string {
  return id === null ? "None" : `#${id}`;
}

export default function SourceMappingQualityPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [items, setItems] = useState<MappingQualityItem[]>([]);
  const [summary, setSummary] = useState<MappingQualitySummary | null>(null);
  const [total, setTotal] = useState(0);

  const [source, setSource] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [isActive, setIsActive] = useState("");
  const [manualVerified, setManualVerified] = useState("");
  const [confidenceLabel, setConfidenceLabel] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [issueType, setIssueType] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [pendingDestructive, setPendingDestructive] = useState<{
    kind: "bulk" | "row";
    action: BulkMappingAction;
    mappingId?: number;
  } | null>(null);
  const [recheckConfirmOpen, setRecheckConfirmOpen] = useState(false);

  const [recheckLimit, setRecheckLimit] = useState(100);
  const [recheckResult, setRecheckResult] = useState<RecheckQualityResult | null>(null);
  const [bulkToolsOpen, setBulkToolsOpen] = useState(false);
  const [bulkResults, setBulkResults] = useState<BulkMappingUpdateResponse | null>(null);

  const [cards, setCards] = useState<Card[]>([]);
  const [detailMapping, setDetailMapping] = useState<MappingQualityItem | null>(null);
  const [detailData, setDetailData] = useState<SuggestedCardsForMapping | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);
  const [cardQuery, setCardQuery] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [pendingCompatibilityEdit, setPendingCompatibilityEdit] = useState<{
    compatibilityCardId: number | null;
  } | null>(null);
  const [compatibilityUpdateResult, setCompatibilityUpdateResult] =
    useState<CompatibilityCardUpdateResult | null>(null);

  useEffect(() => {
    // Each filter change starts a new result set at its first page.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOffset(0);
  }, [source, reviewStatus, isActive, manualVerified, confidenceLabel, riskLevel, issueType, q, limit]);

  function load() {
    let cancelled = false;
    fetchMappingQuality({
      source: source || undefined,
      review_status: reviewStatus || undefined,
      is_active: isActive === "" ? undefined : isActive === "true",
      manual_verified: manualVerified === "" ? undefined : manualVerified === "true",
      confidence_label: confidenceLabel || undefined,
      risk_level: riskLevel || undefined,
      issue_type: issueType || undefined,
      q: q || undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setSummary(data.summary);
        setTotal(data.pagination.total);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }

  useEffect(() => {
    return load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, reviewStatus, isActive, manualVerified, confidenceLabel, riskLevel, issueType, q, limit, offset]);

  useEffect(() => {
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
  }, []);

  const filteredCards = useMemo(() => {
    const query = cardQuery.trim().toLowerCase();
    if (!query) return cards.slice(0, 25);
    return cards
      .filter((card) =>
        [card.card_code, card.name_en, card.name_jp].filter(Boolean).some((f) => f!.toLowerCase().includes(query)),
      )
      .slice(0, 25);
  }, [cards, cardQuery]);

  function updateItem(updated: MappingQualityItem) {
    setItems((prev) => prev.map((i) => (i.mapping_id === updated.mapping_id ? updated : i)));
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllOnPage() {
    setSelected((prev) => {
      const allSelected = items.length > 0 && items.every((i) => prev.has(i.mapping_id));
      if (allSelected) return new Set();
      return new Set(items.map((i) => i.mapping_id));
    });
  }

  async function executeBulkAction(action: BulkMappingAction) {
    setPendingAction(action);
    setActionError(null);
    try {
      const result = await bulkUpdateMappings(Array.from(selected), action, undefined);
      setBulkResults(result);
      load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError(`Failed to apply bulk action: ${action}.`);
    } finally {
      setPendingAction(null);
    }
  }

  function runBulkAction(action: BulkMappingAction) {
    if (selected.size === 0) return;
    if (DESTRUCTIVE_ACTIONS.includes(action)) {
      setPendingDestructive({ kind: "bulk", action });
      return;
    }
    executeBulkAction(action);
  }

  async function runRecheck(dryRun: boolean) {
    setPendingAction(dryRun ? "recheck-dry" : "recheck-real");
    setActionError(null);
    try {
      const result = await recheckMappingQuality({
        source: source || undefined,
        review_status: reviewStatus || undefined,
        is_active: isActive === "" ? undefined : isActive === "true",
        manual_verified: manualVerified === "" ? undefined : manualVerified === "true",
        limit: recheckLimit,
        dry_run: dryRun,
      });
      setRecheckResult(result);
      if (!dryRun) load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to recheck mapping quality.");
    } finally {
      setPendingAction(null);
    }
  }

  function confirmRecheckReal() {
    setRecheckConfirmOpen(false);
    runRecheck(false);
  }

  function openSuggested(item: MappingQualityItem) {
    setDetailMapping(item);
    setDetailData(null);
    setDetailError(null);
    setDetailLoading(true);
    setSelectedCardId(item.compatibility_card_id);
    setCardQuery("");
    setReviewNotes("");
    fetchSuggestedCardsForMapping(item.mapping_id)
      .then(setDetailData)
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setDetailError("Failed to load suggested cards.");
      })
      .finally(() => setDetailLoading(false));
  }

  function closeDetail() {
    setDetailMapping(null);
    setDetailData(null);
    setDetailError(null);
    setPendingCompatibilityEdit(null);
  }

  async function executeCompatibilityEdit(compatibilityCardId: number | null) {
    if (!detailMapping) return;
    setPendingAction(`compatibility-${detailMapping.mapping_id}`);
    setDetailError(null);
    try {
      const updated = await updateMappingCompatibilityCard(
        detailMapping.mapping_id,
        compatibilityCardId,
        reviewNotes.trim() || undefined,
      );
      updateItem(updated);
      setCompatibilityUpdateResult(updated);
      closeDetail();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else {
        setDetailError(
          err instanceof Error
            ? `Compatibility card was not changed: ${err.message}`
            : "Compatibility card was not changed.",
        );
      }
    } finally {
      setPendingAction(null);
    }
  }

  function requestCompatibilityEdit(compatibilityCardId: number | null) {
    if (!detailMapping) return;
    if (detailMapping.identity_classification === "exact") {
      setPendingCompatibilityEdit({ compatibilityCardId });
      return;
    }
    executeCompatibilityEdit(compatibilityCardId);
  }

  function confirmCompatibilityEdit() {
    if (!pendingCompatibilityEdit) return;
    const { compatibilityCardId } = pendingCompatibilityEdit;
    setPendingCompatibilityEdit(null);
    executeCompatibilityEdit(compatibilityCardId);
  }

  async function executeQuickAction(mappingId: number, action: BulkMappingAction) {
    setPendingAction(`row-${mappingId}`);
    setActionError(null);
    try {
      await bulkUpdateMappings([mappingId], action, undefined);
      load();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
      else setActionError("Failed to apply action.");
    } finally {
      setPendingAction(null);
    }
  }

  function quickAction(mappingId: number, action: BulkMappingAction) {
    if (DESTRUCTIVE_ACTIONS.includes(action)) {
      setPendingDestructive({ kind: "row", action, mappingId });
      return;
    }
    executeQuickAction(mappingId, action);
  }

  function confirmDestructive() {
    if (!pendingDestructive) return;
    const { kind, action, mappingId } = pendingDestructive;
    setPendingDestructive(null);
    if (kind === "bulk") executeBulkAction(action);
    else if (mappingId !== undefined) executeQuickAction(mappingId, action);
  }

  const allOnPageSelected = items.length > 0 && items.every((i) => selected.has(i.mapping_id));

  const summaryCards: { label: string; value: number | undefined }[] = summary
    ? [
        { label: "Total mappings", value: summary.total_mappings },
        { label: "Exact print", value: summary.exact_mapping_count },
        { label: "Legacy compatibility", value: summary.legacy_compatibility_mapping_count },
        { label: "Broken identity", value: summary.broken_mapping_count },
        { label: "OK", value: summary.ok_count },
        { label: "Review", value: summary.review_count },
        { label: "Warning", value: summary.warning_count },
        { label: "Critical", value: summary.critical_count },
        { label: "Low confidence", value: summary.low_confidence_count },
        { label: "Duplicate URLs", value: summary.duplicate_source_url_count },
        { label: "Stale mappings", value: summary.stale_mapping_count },
        { label: "Unverified", value: summary.unverified_count },
        { label: "Inactive w/ recent price", value: summary.inactive_with_recent_price_count },
        { label: "Active w/o recent price", value: summary.active_without_recent_price_count },
      ]
    : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Source Mapping Quality"
          description="Review authoritative physical-print identity separately from optional legacy compatibility-card metadata."
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/import-validation" className="text-sky-400 hover:underline">
            Import validation →
          </Link>
          <Link href="/admin/catalog-coverage" className="text-sky-400 hover:underline">
            Catalog coverage →
          </Link>
          <Link href="/admin/price-source-health" className="text-sky-400 hover:underline">
            Price source health →
          </Link>
          <Link href="/admin/catalog-ops" className="text-sky-400 hover:underline">
            Catalog operations →
          </Link>
        </div>

        {unauthorized && <AdminSessionExpired />}

        {!unauthorized && (
          <>
            <QuickActionBar
              actions={[
                { label: "Run Recheck (dry run)", onClick: () => runRecheck(true), variant: "dry-run" },
                { label: "Catalog Ops", href: "/admin/catalog-ops" },
              ]}
            />

            {summary && (
              <StatGrid>
                {summaryCards.map((c) => (
                  <StatCard key={c.label} label={c.label} value={c.value} />
                ))}
              </StatGrid>
            )}

            <FilterBar>
              <select value={source} onChange={(e) => setSource(e.target.value)} className={FILTER_INPUT_CLASS}>
                <option value="">Any source</option>
                <option value="yuyutei">yuyutei</option>
                <option value="snkrdunk">snkrdunk</option>
              </select>
              <select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)} className={FILTER_INPUT_CLASS}>
                {REVIEW_STATUS_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any review status"}
                  </option>
                ))}
              </select>
              <select value={isActive} onChange={(e) => setIsActive(e.target.value)} className={FILTER_INPUT_CLASS}>
                <option value="">Active: any</option>
                <option value="true">Active only</option>
                <option value="false">Inactive only</option>
              </select>
              <select value={manualVerified} onChange={(e) => setManualVerified(e.target.value)} className={FILTER_INPUT_CLASS}>
                <option value="">Verified: any</option>
                <option value="true">Verified only</option>
                <option value="false">Unverified only</option>
              </select>
              <select value={confidenceLabel} onChange={(e) => setConfidenceLabel(e.target.value)} className={FILTER_INPUT_CLASS}>
                {CONFIDENCE_LABEL_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any confidence"}
                  </option>
                ))}
              </select>
              <select value={issueType} onChange={(e) => setIssueType(e.target.value)} className={FILTER_INPUT_CLASS}>
                {ISSUE_TYPE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v || "Any issue type"}
                  </option>
                ))}
              </select>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search URL / source id / card code…"
                className={`w-56 ${FILTER_INPUT_CLASS}`}
              />
            </FilterBar>

            <SavedViewBar
              routePath="/admin/source-mapping-quality"
              viewType="source_mapping_quality"
              scope="admin"
              currentFilters={{
                source,
                reviewStatus,
                isActive,
                manualVerified,
                confidenceLabel,
                riskLevel,
                issueType,
                q,
              }}
              onApply={(filters) => {
                if (typeof filters.source === "string") setSource(filters.source);
                if (typeof filters.reviewStatus === "string") setReviewStatus(filters.reviewStatus);
                if (typeof filters.isActive === "string") setIsActive(filters.isActive);
                if (typeof filters.manualVerified === "string") {
                  setManualVerified(filters.manualVerified);
                }
                if (typeof filters.confidenceLabel === "string") {
                  setConfidenceLabel(filters.confidenceLabel);
                }
                if (typeof filters.riskLevel === "string") setRiskLevel(filters.riskLevel);
                if (typeof filters.issueType === "string") setIssueType(filters.issueType);
                if (typeof filters.q === "string") setQ(filters.q);
                setOffset(0);
              }}
            />

            <div className="mb-4 flex flex-wrap gap-1">
              {RISK_FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setRiskLevel(f.value)}
                  className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                    riskLevel === f.value
                      ? "bg-accent-gold text-black/80 ring-accent-gold"
                      : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                  }`}
                >
                  {f.label}
                </button>
              ))}
              <ActionButton className="ml-auto" onClick={() => setBulkToolsOpen((v) => !v)}>
                {bulkToolsOpen ? "Hide bulk tools" : "Bulk tools…"}
              </ActionButton>
            </div>

            {bulkToolsOpen && (
              <AdminActionPanel
                description="Recheck quality (uses current source/review/active/verified filters):"
              >
                <div className="flex w-full flex-wrap items-center gap-2">
                  <input
                    type="number"
                    value={recheckLimit}
                    onChange={(e) => setRecheckLimit(Number(e.target.value) || 100)}
                    className={`w-24 ${FILTER_INPUT_CLASS}`}
                  />
                  <ActionButton
                    variant="dry-run"
                    onClick={() => runRecheck(true)}
                    disabled={pendingAction === "recheck-dry"}
                  >
                    Dry run
                  </ActionButton>
                  <ActionButton
                    variant="danger"
                    onClick={() => setRecheckConfirmOpen(true)}
                    disabled={pendingAction === "recheck-real"}
                  >
                    Apply real run
                  </ActionButton>
                </div>
                {recheckResult && (
                  <div className="mt-3 flex w-full flex-wrap gap-4 text-xs text-text-secondary">
                    <span>dry_run: {String(recheckResult.dry_run)}</span>
                    <span>selected: {recheckResult.summary.selected}</span>
                    <span>would_update: {recheckResult.summary.would_update}</span>
                    <span>updated: {recheckResult.summary.updated}</span>
                    <span>ok: {recheckResult.summary.ok}</span>
                    <span>review: {recheckResult.summary.review}</span>
                    <span>warning: {recheckResult.summary.warning}</span>
                    <span>critical: {recheckResult.summary.critical}</span>
                  </div>
                )}

                <div className="mt-3 w-full text-xs text-text-muted">
                  Bulk actions apply to {selected.size} selected mapping{selected.size === 1 ? "" : "s"}:
                </div>
                <div className="flex w-full flex-wrap gap-2">
                  {BULK_ACTIONS.map((a) => (
                    <ActionButton
                      key={a.action}
                      variant={a.variant}
                      onClick={() => runBulkAction(a.action)}
                      disabled={selected.size === 0 || pendingAction === a.action}
                    >
                      {a.label}
                    </ActionButton>
                  ))}
                </div>
                {bulkResults && (
                  <div className="mt-3 w-full text-xs text-text-secondary">
                    {bulkResults.action}: {bulkResults.results.filter((r) => r.ok).length}/{bulkResults.results.length} succeeded
                    {bulkResults.results.some((r) => !r.ok) && (
                      <span className="text-signal-red">
                        {" "}
                        (skipped/failed:{" "}
                        {bulkResults.results
                          .filter((r) => !r.ok)
                          .map((r) => `${r.mapping_id}: ${r.error ?? "unknown error"}`)
                          .join(", ")})
                      </span>
                    )}
                  </div>
                )}
              </AdminActionPanel>
            )}

            {actionError && (
              <div className="mb-4 rounded-panel border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">{actionError}</div>
            )}

            {compatibilityUpdateResult && (
              <div className="mb-4 rounded-panel border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
                <div className="font-medium">Compatibility card updated; pricing identity was unchanged.</div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <span>Authoritative CardPrint: {idLabel(compatibilityUpdateResult.authoritative_card_print_id)}</span>
                  <span>Previous compatibility card: {idLabel(compatibilityUpdateResult.previous_compatibility_card_id)}</span>
                  <span>New compatibility card: {idLabel(compatibilityUpdateResult.new_compatibility_card_id)}</span>
                  <span className="mono">pricing_identity_changed=false</span>
                </div>
              </div>
            )}

            {status === "loading" && <LoadingState>Loading mappings…</LoadingState>}
            {status === "error" && (
              <ErrorState>Failed to load source mappings from the API. Is the backend running?</ErrorState>
            )}

            {status === "ready" && (
              <DataTableShell isEmpty={items.length === 0} emptyLabel="No mappings found.">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>
                        <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelectAllOnPage} />
                      </th>
                      <th>Risk</th>
                      <th>Issues</th>
                      <th>Source</th>
                      <th>Identity classification</th>
                      <th>Authoritative physical print</th>
                      <th>Compatibility metadata</th>
                      <th>URL</th>
                      <th>Active</th>
                      <th>Verified</th>
                      <th>Review</th>
                      <th>Confidence scope</th>
                      <th>Latest price</th>
                      <th>Last checked</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.mapping_id}>
                        <td>
                          <input type="checkbox" checked={selected.has(item.mapping_id)} onChange={() => toggleSelect(item.mapping_id)} />
                        </td>
                        <td>
                          <RiskBadge level={item.risk_level} />
                        </td>
                        <td className="max-w-[12rem]">
                          <div className="flex flex-wrap gap-1">
                            {item.issue_types.map((t) => (
                              <span key={t} className="rounded-control bg-bg-elevated px-1.5 py-0.5 text-[11px] text-text-secondary">
                                {t}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="text-text-secondary">{item.source_name ?? "—"}</td>
                        <td><IdentityClassification item={item} /></td>
                        <td><AuthoritativePrintIdentity item={item} /></td>
                        <td><CompatibilityCardIdentity item={item} /></td>
                        <td className="max-w-[10rem] truncate">
                          {item.source_url ? (
                            <a href={item.source_url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                              link
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="text-text-secondary">{item.is_active ? "yes" : "no"}</td>
                        <td className="text-text-secondary">{item.manual_verified ? "yes" : "no"}</td>
                        <td className="text-text-secondary">{item.review_status}</td>
                        <td><MappingConfidence item={item} /></td>
                        <td className="mono text-xs text-text-muted">{formatDateTime(item.latest_price_observed_at)}</td>
                        <td className="mono text-xs text-text-muted">{formatDateTime(item.last_match_checked_at)}</td>
                        <td>
                          <div className="flex flex-wrap gap-1.5">
                            <ActionButton onClick={() => openSuggested(item)}>Edit compatibility card</ActionButton>
                            <ActionButton
                              onClick={() => quickAction(item.mapping_id, "approve")}
                              disabled={pendingAction === `row-${item.mapping_id}`}
                            >
                              Approve
                            </ActionButton>
                            <ActionButton
                              variant="danger"
                              onClick={() => quickAction(item.mapping_id, "reject")}
                              disabled={pendingAction === `row-${item.mapping_id}`}
                            >
                              Reject
                            </ActionButton>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
            )}

            {status === "ready" && (
              <div className="mt-3">
                <PaginationControls offset={offset} limit={limit} total={total} onOffsetChange={setOffset} limitOptions={LIMIT_OPTIONS} onLimitChange={setLimit} />
              </div>
            )}
          </>
        )}

        {detailMapping && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-5">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-text-primary">Edit compatibility card</h2>
                  <div className="text-xs text-text-muted">
                    Mapping {detailMapping.mapping_id} — {detailMapping.source_card_id}
                  </div>
                  {detailMapping.source_url && (
                    <a href={detailMapping.source_url} target="_blank" rel="noreferrer" className="text-xs text-sky-400 hover:underline">
                      {detailMapping.source_url}
                    </a>
                  )}
                </div>
                <button onClick={closeDetail} className="rounded px-2 py-1 text-xs font-medium text-text-secondary hover:text-text-primary">
                  Close
                </button>
              </div>

              <div className="mb-4 grid gap-3 md:grid-cols-2">
                <div className="panel p-3">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                    Authoritative pricing identity
                  </div>
                  <IdentityClassification item={detailMapping} />
                  <div className="mt-2"><AuthoritativePrintIdentity item={detailMapping} /></div>
                  {detailMapping.identity_classification === "exact" && (
                    <p className="mt-2 text-xs text-emerald-300">
                      This physical print remains unchanged by compatibility-card edits.
                    </p>
                  )}
                </div>
                <div className="panel p-3">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                    Legacy compatibility metadata
                  </div>
                  <CompatibilityCardIdentity item={detailMapping} />
                  <p className="mt-2 text-xs text-text-muted">
                    Editing this metadata does not change pricing history, Market Index identity, or Card Pirate Index identity.
                  </p>
                </div>
              </div>

              <div className="panel mb-4 p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                  Confidence
                </div>
                <MappingConfidence item={detailMapping} />
              </div>

              {detailLoading && <p className="p-6 text-center text-sm text-text-muted">Loading suggested cards…</p>}
              {detailError && (
                <div className="rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-sm text-signal-red">
                  {detailError}
                </div>
              )}

              {!detailLoading && detailData && (
                <>
                  <div className="mb-3 rounded-control border border-border-default bg-bg-page p-3 text-xs text-text-secondary">
                    {detailData.message}
                  </div>
                  {detailData.matches.length === 0 && (
                    <EmptyState>No compatibility-card suggestions available.</EmptyState>
                  )}
                  <div className="mb-4 space-y-2">
                    {detailData.matches.map((match) => (
                      <div key={match.card_id} className="panel p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-medium text-text-primary">
                            <span className="mono">{match.card_code}</span> — {match.name_en ?? match.name_jp}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="mono tabular text-xs text-text-secondary">
                              score {match.score} ({match.confidence_label})
                            </span>
                            <ActionButton
                              onClick={() => requestCompatibilityEdit(match.card_id)}
                              disabled={pendingAction === `compatibility-${detailMapping.mapping_id}`}
                            >
                              Use as compatibility card
                            </ActionButton>
                          </div>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                          {match.explanation.positive.map((p) => (
                            <span key={p} className="text-emerald-400">
                              + {p}
                            </span>
                          ))}
                          {match.explanation.negative.map((n) => (
                            <span key={n} className="text-signal-red">
                              − {n}
                            </span>
                          ))}
                          {match.explanation.caps_applied.map((c) => (
                            <span key={c} className="text-signal-warning">
                              cap: {c}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="panel mb-3 p-3">
                    <div className="mb-1 text-xs font-medium text-text-secondary">Edit compatibility card</div>
                    <p className="mb-3 text-xs text-text-muted">
                      This changes legacy compatibility metadata only. The authoritative CardPrint shown above is read-only and remains unchanged.
                    </p>
                    <FilterBar>
                      <input
                        value={cardQuery}
                        onChange={(e) => setCardQuery(e.target.value)}
                        placeholder="Search by card code or name…"
                        className={`w-56 ${FILTER_INPUT_CLASS}`}
                      />
                      <select
                        value={selectedCardId ?? ""}
                        onChange={(e) => setSelectedCardId(e.target.value ? Number(e.target.value) : null)}
                        className={`w-64 ${FILTER_INPUT_CLASS}`}
                      >
                        <option value="">
                          {detailMapping.identity_classification === "exact"
                            ? "None (clear compatibility card)"
                            : "Select a compatibility card…"}
                        </option>
                        {filteredCards.map((card) => (
                          <option key={card.id} value={card.id}>
                            {card.card_code} — {cardDisplayName(card)}
                          </option>
                        ))}
                      </select>
                      <input
                        value={reviewNotes}
                        onChange={(e) => setReviewNotes(e.target.value)}
                        placeholder="Review notes (optional)…"
                        className={`w-56 ${FILTER_INPUT_CLASS}`}
                      />
                      <ActionButton
                        variant="primary"
                        onClick={() => requestCompatibilityEdit(selectedCardId)}
                        disabled={
                          (selectedCardId === null && detailMapping.identity_classification !== "exact") ||
                          pendingAction === `compatibility-${detailMapping.mapping_id}`
                        }
                      >
                        Save compatibility card
                      </ActionButton>
                    </FilterBar>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        <ConfirmActionModal
          open={pendingCompatibilityEdit !== null}
          title="Confirm compatibility-card edit"
          description="Compatibility metadata will change. The authoritative physical-print identity will remain unchanged."
          affectedRecords={
            detailMapping && pendingCompatibilityEdit
              ? [
                  { label: "Authoritative CardPrint", value: idLabel(detailMapping.card_print_id) },
                  { label: "Current compatibility card", value: idLabel(detailMapping.compatibility_card_id) },
                  { label: "New compatibility card", value: idLabel(pendingCompatibilityEdit.compatibilityCardId) },
                ]
              : undefined
          }
          confirmLabel="Save compatibility card"
          pending={detailMapping ? pendingAction === `compatibility-${detailMapping.mapping_id}` : false}
          onConfirm={confirmCompatibilityEdit}
          onCancel={() => setPendingCompatibilityEdit(null)}
        />

        <ConfirmActionModal
          open={pendingDestructive !== null}
          title={pendingDestructive ? `${destructiveLabel(pendingDestructive.action)} mapping${pendingDestructive.kind === "bulk" ? "s" : ""}` : ""}
          description={
            pendingDestructive?.kind === "bulk"
              ? `${destructiveLabel(pendingDestructive.action)} ${selected.size} selected mapping${selected.size === 1 ? "" : "s"}? This cannot be undone from here.`
              : `${pendingDestructive ? destructiveLabel(pendingDestructive.action) : ""} this mapping?`
          }
          confirmLabel={pendingDestructive ? destructiveLabel(pendingDestructive.action) : "Confirm"}
          onConfirm={confirmDestructive}
          onCancel={() => setPendingDestructive(null)}
        />

        <ConfirmActionModal
          open={recheckConfirmOpen}
          title="Apply real recheck run"
          description="This updates risk/confidence scoring for mappings matching the current filters. Dry-run first to preview affected counts."
          affectedRecords={
            recheckResult
              ? [
                  { label: "selected", value: recheckResult.summary.selected },
                  { label: "would_update", value: recheckResult.summary.would_update },
                ]
              : undefined
          }
          confirmPhrase="RUN"
          confirmLabel="Apply real run"
          pending={pendingAction === "recheck-real"}
          onConfirm={confirmRecheckReal}
          onCancel={() => setRecheckConfirmOpen(false)}
        />
      </main>
    </div>
  );
}
