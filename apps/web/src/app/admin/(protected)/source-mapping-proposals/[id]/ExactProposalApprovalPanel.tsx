"use client";

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { formatDateTime } from "@/lib/format";
import { maskReviewer } from "@/lib/maskReviewer";
import {
  ProposalApprovalError,
  approveExactProposal,
  type ApproveExactProposalResponse,
  type ProposalReviewAlternative,
  type ProposalReviewGroupDetail,
} from "@/lib/proposalReview";

import {
  KeyValue,
  KeyValueGrid,
  ProposalArtwork,
  releaseDisplayName,
} from "../ProposalReviewComponents";

const REVIEW_NOTE_MAX_LENGTH = 2000;
const STALE_CODES = new Set([
  "proposal_superseded",
  "proposal_not_pending",
  "evidence_digest_changed",
  "resolver_version_changed",
  "proposal_updated",
  "proposal_result_changed",
  "candidate_state_changed",
  "release_changed",
  "source_identity_changed",
]);
const REFUSAL_CODES = new Set([
  "print_inactive",
  "print_unverified",
  "existing_mapping_names_another_print",
  "existing_mapping_was_rejected",
  "multiple_mappings_for_listing",
  "evidence_contradicts_selection",
]);

type Eligibility =
  | { eligible: true; alternative: ProposalReviewAlternative }
  | { eligible: false; message: string | null };

export function exactApprovalEligibility(proposal: ProposalReviewGroupDetail): Eligibility {
  if (proposal.review_status === "approved") return { eligible: false, message: null };
  if (proposal.review_status === "rejected") {
    return { eligible: false, message: "This proposal has a terminal rejected decision. Exact approval is unavailable." };
  }
  if (proposal.superseded_at || proposal.resolution_status === "superseded") {
    return { eligible: false, message: "This proposal has been superseded. Review the current proposal instead." };
  }
  if (proposal.resolution_status === "ambiguous") {
    return { eligible: false, message: "Exact approval is unavailable because multiple physical printings remain." };
  }
  if (proposal.resolution_status === "unresolved_identity") {
    return { eligible: false, message: "Exact approval is unavailable because no canonical card identity has been established." };
  }
  if (proposal.resolution_status === "release_unresolved") {
    return { eligible: false, message: "Exact approval is unavailable because no authoritative release product has been established." };
  }
  if (proposal.resolution_status !== "exact") {
    return { eligible: false, message: `Exact approval is unavailable while this proposal is ${proposal.resolution_status.replaceAll("_", " ")}.` };
  }
  if (proposal.review_status !== "pending") {
    return { eligible: false, message: "Exact approval is unavailable for this proposal lifecycle state." };
  }
  if (proposal.resulting_source_card_mapping_id !== null || proposal.resulting_mapping !== null) {
    return { eligible: false, message: "A resulting mapping is already linked. No new approval action is available." };
  }
  if (proposal.alternatives.length !== 1 || proposal.alternative_count !== 1) {
    return {
      eligible: false,
      message: proposal.alternatives.length === 0 || proposal.alternative_count === 0
        ? "Exact approval is blocked because this proposal has no printing alternative."
        : "Exact approval is blocked because this exact proposal unexpectedly has multiple printing alternatives.",
    };
  }
  const recommended = proposal.alternatives.filter((alternative) => alternative.recommended);
  if (recommended.length !== 1 || proposal.recommended_alternative_count !== 1) {
    return { eligible: false, message: "Exact approval is blocked because there is not exactly one recommended printing." };
  }
  const alternative = proposal.alternatives[0];
  if (alternative.proposal_group_id !== proposal.id) {
    return { eligible: false, message: "Exact approval is blocked because the printing does not belong to this proposal." };
  }
  if (alternative.review_disposition !== "pending") {
    return { eligible: false, message: "Exact approval is blocked because the selected printing is no longer pending." };
  }
  if (!proposal.evidence_digest) {
    return { eligible: false, message: "Exact approval is blocked because the evidence digest is missing." };
  }
  if (!proposal.resolver_version.trim()) {
    return { eligible: false, message: "Exact approval is blocked because the resolver version is missing." };
  }
  if (!proposal.updated_at) {
    return { eligible: false, message: "Exact approval is blocked because the proposal update time is missing." };
  }
  return { eligible: true, alternative };
}

interface ApprovalNotice {
  tone: "error" | "warning";
  message: string;
  reload: boolean;
}

export function ExactProposalApprovalPanel({
  proposal,
  onReload,
}: {
  proposal: ProposalReviewGroupDetail;
  onReload: (options?: { silent?: boolean }) => void;
}) {
  const eligibility = exactApprovalEligibility(proposal);
  if (proposal.review_status === "approved") {
    return <ApprovedDecision proposal={proposal} />;
  }
  if (!eligibility.eligible) {
    return eligibility.message ? <BlockedDecision message={eligibility.message} /> : null;
  }
  const proposalSignature = [
    proposal.id,
    proposal.updated_at,
    proposal.evidence_digest,
    proposal.resolver_version,
    proposal.review_status,
    proposal.resulting_source_card_mapping_id ?? "none",
    proposal.alternatives.map((alternative) => `${alternative.alternative_id}:${alternative.updated_at}`).join(","),
  ].join("|");
  return (
    <EligibleExactProposalApprovalPanel
      key={proposalSignature}
      proposal={proposal}
      alternative={eligibility.alternative}
      onReload={onReload}
    />
  );
}

function EligibleExactProposalApprovalPanel({
  proposal,
  alternative,
  onReload,
}: {
  proposal: ProposalReviewGroupDetail;
  alternative: ProposalReviewAlternative;
  onReload: (options?: { silent?: boolean }) => void;
}) {
  const router = useRouter();
  const [selectedAlternativeId, setSelectedAlternativeId] = useState<number | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [acknowledgedEvidence, setAcknowledgedEvidence] = useState(false);
  const [acknowledgedCollection, setAcknowledgedCollection] = useState(false);
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<ApprovalNotice | null>(null);
  const [result, setResult] = useState<ApproveExactProposalResponse | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const submitLockedRef = useRef(false);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  const closeModal = useCallback((discardDraft: boolean) => {
    if (submitLockedRef.current) return;
    setModalOpen(false);
    setAcknowledgedEvidence(false);
    setAcknowledgedCollection(false);
    setConfirmationPhrase("");
    if (discardDraft) {
      setReviewNote("");
    }
    requestAnimationFrame(() => openerRef.current?.focus());
  }, []);

  const expectedPhrase = `APPROVE PROPOSAL ${proposal.id}`;
  const selected = selectedAlternativeId === alternative.alternative_id;
  const canOpen = selected && !pending && !notice?.reload;
  const canSubmit =
    selected &&
    acknowledgedEvidence &&
    acknowledgedCollection &&
    confirmationPhrase.trim() === expectedPhrase &&
    !pending;
  const cardName = alternative.canonical_card.name_en ?? alternative.canonical_card.name_jp ?? alternative.canonical_card.card_code;

  function openConfirmation() {
    if (!canOpen) return;
    setNotice(null);
    setAcknowledgedEvidence(false);
    setAcknowledgedCollection(false);
    setConfirmationPhrase("");
    setModalOpen(true);
  }

  function reloadProposal() {
    if (pending) return;
    setSelectedAlternativeId(null);
    setModalOpen(false);
    setNotice(null);
    setResult(null);
    onReload();
    router.refresh();
  }

  async function submitApproval() {
    if (!canSubmit || submitLockedRef.current) return;
    submitLockedRef.current = true;
    setPending(true);
    setNotice(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const normalizedNote = reviewNote.trim();
    try {
      const response = await approveExactProposal(
        proposal.id,
        {
          selected_alternative_id: alternative.alternative_id,
          expected_evidence_digest: proposal.evidence_digest,
          expected_resolver_version: proposal.resolver_version,
          expected_updated_at: proposal.updated_at,
          ...(normalizedNote ? { review_note: normalizedNote } : {}),
        },
        { signal: controller.signal },
      );
      if (
        response.proposal_group_id !== proposal.id ||
        response.selected_alternative_id !== alternative.alternative_id ||
        response.card_print_id !== alternative.card_print_id ||
        response.review_status !== "approved" ||
        response.collection_triggered !== false ||
        response.price_observation_written !== false
      ) {
        throw new ProposalApprovalError({
          message: "The approval response did not match the proposal shown on this page.",
          status: 0,
          code: "response_mismatch",
          uncertain: true,
        });
      }
      setResult(response);
      setReviewNote("");
      setSelectedAlternativeId(null);
      setModalOpen(false);
      setAcknowledgedEvidence(false);
      setAcknowledgedCollection(false);
      setConfirmationPhrase("");
      router.refresh();
      onReload({ silent: true });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setModalOpen(false);
      setNotice(approvalErrorNotice(error));
      requestAnimationFrame(() => openerRef.current?.focus());
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      submitLockedRef.current = false;
      setPending(false);
    }
  }

  return (
    <section className="rounded-panel border border-amber-500/35 bg-amber-500/5 p-4" aria-labelledby="exact-approval-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="exact-approval-heading" className="text-lg font-semibold text-text-primary">Approve exact proposal</h2>
          <p className="mt-1 text-xs font-medium uppercase tracking-wide text-amber-200">Eligible for exact-approval review</p>
        </div>
        <span className="rounded-control border border-amber-500/35 bg-amber-500/10 px-2 py-1 text-xs text-amber-200">Single proposal only</span>
      </div>

      <p className="mt-4 rounded-control border border-amber-500/30 bg-bg-page p-3 text-sm text-amber-100">
        Approval creates or activates a collector-facing mapping for this exact printing. It does not collect a price immediately. The mapping becomes eligible for a future scheduled collector run.
      </p>

      <div className="mt-4 flex flex-col gap-5 lg:flex-row">
        <ProposalArtwork print={alternative} alt={`${cardName} ${alternative.printing_label ?? "printing"} selected artwork`} size="detail" />
        <div className="min-w-0 flex-1 space-y-5">
          <KeyValueGrid>
            <KeyValue label="Proposal ID">{proposal.id}</KeyValue>
            <KeyValue label="Source">{proposal.source_name}</KeyValue>
            <KeyValue label="Source candidate ID">{proposal.source_candidate_id}</KeyValue>
            <KeyValue label="Canonical listing identity">{proposal.canonical_source_listing_identity}</KeyValue>
            <KeyValue label="Card code">{proposal.card_code ?? alternative.canonical_card.card_code}</KeyValue>
            <KeyValue label="English / Japanese name">{[proposal.name_en, proposal.name_jp].filter(Boolean).join(" / ") || cardName}</KeyValue>
            <KeyValue label="Authoritative release">{releaseDisplayName(proposal.release)}</KeyValue>
            <KeyValue label="Selected alternative ID">{alternative.alternative_id}</KeyValue>
            <KeyValue label="CardPrint ID">{alternative.card_print_id}</KeyValue>
            <KeyValue label="Asset variant / printing">{[alternative.official_asset_variant, alternative.printing_label].filter(Boolean).join(" / ") || "Not stored"}</KeyValue>
            <KeyValue label="Resolver version">{proposal.resolver_version}</KeyValue>
            <KeyValue label="Evidence digest"><span className="mono">{shortDigest(proposal.evidence_digest)}</span></KeyValue>
            <KeyValue label="Proposal updated">{formatDateTime(proposal.updated_at)}</KeyValue>
          </KeyValueGrid>

          <fieldset>
            <legend className="text-sm font-semibold text-text-primary">Select the exact physical printing</legend>
            <label className="mt-2 flex cursor-pointer gap-3 rounded-control border border-border-default bg-bg-page p-3 text-sm focus-within:ring-2 focus-within:ring-accent-teal/60">
              <input
                type="radio"
                name={`proposal-${proposal.id}-alternative`}
                value={alternative.alternative_id}
                checked={selected}
                onChange={() => {
                  setSelectedAlternativeId(alternative.alternative_id);
                  setNotice(null);
                }}
                disabled={pending}
                className="mt-1 h-4 w-4 accent-sky-400"
              />
              <span>
                <span className="block font-medium text-text-primary">{cardName} · CardPrint #{alternative.card_print_id}</span>
                <span className="mt-1 block text-text-secondary">{alternative.printing_label ?? "Exact printing"} · {releaseDisplayName(alternative.release)}</span>
              </span>
            </label>
            <p className="mt-2 text-xs text-text-muted">The recommended printing is not selected automatically. Inspect the evidence and artwork before selecting it.</p>
          </fieldset>

          <div>
            <label htmlFor={`review-note-${proposal.id}`} className="block text-sm font-medium text-text-primary">Review note <span className="font-normal text-text-muted">(optional)</span></label>
            <textarea
              id={`review-note-${proposal.id}`}
              value={reviewNote}
              onChange={(event) => setReviewNote(event.target.value)}
              maxLength={REVIEW_NOTE_MAX_LENGTH}
              rows={4}
              disabled={pending}
              className="mt-2 w-full rounded-control border border-border-default bg-bg-page px-3 py-2 text-sm text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:opacity-50"
            />
            <p className="mt-1 text-xs text-text-muted">{reviewNote.length}/{REVIEW_NOTE_MAX_LENGTH} characters. Reviewer identity comes from your verified admin session.</p>
          </div>

          <div aria-live="assertive" aria-atomic="true">
            {notice && (
              <div className={`rounded-control border p-3 text-sm ${notice.tone === "warning" ? "border-amber-500/35 bg-amber-500/10 text-amber-100" : "border-rose-500/35 bg-rose-500/10 text-rose-200"}`}>
                <p>{notice.message}</p>
                {notice.reload && <ActionButton className="mt-3" onClick={reloadProposal}>Reload proposal</ActionButton>}
              </div>
            )}
            {result && <ApprovalResult result={result} />}
          </div>

          <ActionButton
            ref={openerRef}
            variant="real"
            disabled={!canOpen}
            onClick={openConfirmation}
            className="px-4 py-2 text-sm"
          >
            Review approval confirmation
          </ActionButton>
        </div>
      </div>

      {modalOpen && (
        <ApprovalConfirmationModal
          proposal={proposal}
          alternative={alternative}
          expectedPhrase={expectedPhrase}
          acknowledgedEvidence={acknowledgedEvidence}
          acknowledgedCollection={acknowledgedCollection}
          confirmationPhrase={confirmationPhrase}
          pending={pending}
          canSubmit={canSubmit}
          onAcknowledgedEvidence={setAcknowledgedEvidence}
          onAcknowledgedCollection={setAcknowledgedCollection}
          onConfirmationPhrase={setConfirmationPhrase}
          onConfirm={submitApproval}
          onCancel={() => closeModal(true)}
        />
      )}
    </section>
  );
}

function ApprovalConfirmationModal({
  proposal,
  alternative,
  expectedPhrase,
  acknowledgedEvidence,
  acknowledgedCollection,
  confirmationPhrase,
  pending,
  canSubmit,
  onAcknowledgedEvidence,
  onAcknowledgedCollection,
  onConfirmationPhrase,
  onConfirm,
  onCancel,
}: {
  proposal: ProposalReviewGroupDetail;
  alternative: ProposalReviewAlternative;
  expectedPhrase: string;
  acknowledgedEvidence: boolean;
  acknowledgedCollection: boolean;
  confirmationPhrase: string;
  pending: boolean;
  canSubmit: boolean;
  onAcknowledgedEvidence: (checked: boolean) => void;
  onAcknowledgedCollection: (checked: boolean) => void;
  onConfirmationPhrase: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const phraseHelpId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cardName = alternative.canonical_card.name_en ?? alternative.canonical_card.name_jp ?? alternative.canonical_card.card_code;

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !pending) {
        event.preventDefault();
        onCancel();
      }
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [onCancel, pending]);

  function keepFocusInside(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    );
    if (!controls?.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 sm:p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={pending}
        tabIndex={-1}
        onKeyDown={keepFocusInside}
        className="max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-4 outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 sm:max-h-[90vh] sm:p-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-text-primary">Confirm exact proposal approval</h2>
            <p id={descriptionId} className="mt-1 text-sm text-text-secondary">One final review is required before this mapping decision is sent.</p>
          </div>
          <button type="button" onClick={onCancel} disabled={pending} className="rounded-control px-2 py-1 text-xs font-medium text-text-muted hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:opacity-40">Close</button>
        </div>

        <div className="mt-4 flex flex-col gap-4 sm:flex-row">
          <ProposalArtwork print={alternative} alt={`${cardName} ${alternative.printing_label ?? "printing"} approval artwork`} size="detail" />
          <div className="min-w-0 flex-1">
            <KeyValueGrid>
              <KeyValue label="Proposal ID">{proposal.id}</KeyValue>
              <KeyValue label="Card">{alternative.canonical_card.card_code} · {cardName}</KeyValue>
              <KeyValue label="Source">{proposal.source_name}</KeyValue>
              <KeyValue label="Authoritative release">{releaseDisplayName(proposal.release)}</KeyValue>
              <KeyValue label="CardPrint ID">{alternative.card_print_id}</KeyValue>
            </KeyValueGrid>
          </div>
        </div>

        <p className="mt-4 rounded-control border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
          Approval authorizes this exact printing for future scheduled collection. It does not run a collector or create a price now.
        </p>

        <div className="mt-4 space-y-3">
          <label className="flex gap-3 text-sm text-text-primary">
            <input type="checkbox" checked={acknowledgedEvidence} onChange={(event) => onAcknowledgedEvidence(event.target.checked)} disabled={pending} className="mt-1 h-4 w-4 accent-sky-400" />
            <span>I reviewed the source evidence and the exact physical printing.</span>
          </label>
          <label className="flex gap-3 text-sm text-text-primary">
            <input type="checkbox" checked={acknowledgedCollection} onChange={(event) => onAcknowledgedCollection(event.target.checked)} disabled={pending} className="mt-1 h-4 w-4 accent-sky-400" />
            <span>I understand this authorizes future scheduled collection but does not collect or create a price now.</span>
          </label>
          <div>
            <label htmlFor={`approval-phrase-${proposal.id}`} className="block text-sm font-medium text-text-primary">Typed confirmation</label>
            <p id={phraseHelpId} className="mt-1 text-xs text-text-muted">Type <span className="mono text-text-primary">{expectedPhrase}</span> exactly.</p>
            <input
              id={`approval-phrase-${proposal.id}`}
              value={confirmationPhrase}
              onChange={(event) => onConfirmationPhrase(event.target.value)}
              aria-describedby={phraseHelpId}
              autoComplete="off"
              spellCheck={false}
              disabled={pending}
              className="mt-2 w-full rounded-control border border-border-default bg-bg-page px-3 py-2 text-sm text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:opacity-50"
            />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <ActionButton variant="danger" disabled={!canSubmit} onClick={onConfirm} className="px-4 py-2 text-sm">
            {pending ? "Approving exact proposal…" : "Approve exact proposal"}
          </ActionButton>
          <ActionButton disabled={pending} onClick={onCancel} className="px-4 py-2 text-sm">Cancel</ActionButton>
        </div>
      </div>
    </div>
  );
}

function ApprovalResult({ result }: { result: ApproveExactProposalResponse }) {
  return (
    <div className="mb-4 rounded-control border border-emerald-500/35 bg-emerald-500/10 p-3 text-sm text-emerald-100" role="status">
      <h3 className="font-semibold">Approved</h3>
      {result.idempotent_replay && <p className="mt-2">This exact approval was already recorded. No duplicate mapping or decision was created.</p>}
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <DecisionValue label="Reviewer" value={maskReviewer(result.reviewed_by)} />
        <DecisionValue label="Reviewed" value={formatDateTime(result.reviewed_at)} />
        <DecisionValue label="Resulting mapping" value={`Mapping #${result.resulting_source_card_mapping_id}`} />
        <DecisionValue label="Mapping result" value={result.mapping_created ? "Created" : result.mapping_reused ? "Reused" : "Existing mapping retained"} />
        <DecisionValue label="Candidate status" value={result.candidate_status} />
        <DecisionValue label="Scheduled collection" value={result.eligible_for_future_scheduled_collection ? "Eligible for a future run" : "Not eligible"} />
      </dl>
      <p className="mt-3">No immediate collection was triggered. No price observation was written.</p>
    </div>
  );
}

function ApprovedDecision({ proposal }: { proposal: ProposalReviewGroupDetail }) {
  const selected = proposal.alternatives.find((alternative) => alternative.alternative_id === proposal.selected_alternative_id) ?? null;
  return (
    <section className="rounded-panel border border-emerald-500/35 bg-emerald-500/5 p-4" aria-labelledby="approved-decision-heading">
      <h2 id="approved-decision-heading" className="text-lg font-semibold text-emerald-200">Approved</h2>
      <p className="mt-1 text-sm text-text-secondary">This phase-one decision is terminal. Eligible for future scheduled collection.</p>
      <div className="mt-4 flex flex-col gap-4 sm:flex-row">
        {selected && <ProposalArtwork print={selected} alt={`${selected.canonical_card.card_code} approved printing artwork`} size="detail" />}
        <KeyValueGrid>
          <KeyValue label="Selected printing">{selected ? `${selected.canonical_card.card_code} · CardPrint #${selected.card_print_id}` : `Alternative #${proposal.selected_alternative_id ?? "not returned"}`}</KeyValue>
          <KeyValue label="Resulting mapping">{proposal.resulting_source_card_mapping_id ? `Mapping #${proposal.resulting_source_card_mapping_id}` : "Not returned"}</KeyValue>
          <KeyValue label="Reviewer">{maskReviewer(proposal.reviewed_by)}</KeyValue>
          <KeyValue label="Reviewed time">{formatDateTime(proposal.reviewed_at)}</KeyValue>
          <KeyValue label="Review note">{proposal.review_notes ?? "None"}</KeyValue>
          <KeyValue label="Decision basis">{formatDateTime(proposal.decision_basis_updated_at)}</KeyValue>
          <KeyValue label="Candidate status">{proposal.candidate.match_status ?? "Not stored"}</KeyValue>
        </KeyValueGrid>
      </div>
    </section>
  );
}

function BlockedDecision({ message }: { message: string }) {
  return (
    <section className="rounded-panel border border-border-default bg-bg-surface p-4" aria-labelledby="approval-unavailable-heading">
      <h2 id="approval-unavailable-heading" className="text-base font-semibold text-text-primary">Exact approval unavailable</h2>
      <p className="mt-2 text-sm text-text-secondary">{message}</p>
    </section>
  );
}

function DecisionValue({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-emerald-200/75">{label}</dt><dd className="text-emerald-50">{value}</dd></div>;
}

function shortDigest(digest: string): string {
  return digest.length > 20 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function approvalErrorNotice(error: unknown): ApprovalNotice {
  if (!(error instanceof ProposalApprovalError)) {
    return {
      tone: "warning",
      message: "The approval result is uncertain. Reload the proposal and review its current state before trying again. Nothing will be resent automatically.",
      reload: true,
    };
  }
  if (error.status === 401 || error.code === "admin_actor_assertion_required" || error.code === "admin_actor_assertion_invalid" || error.code === "admin_actor_assertion_expired" || error.code === "admin_actor_assertion_request_mismatch") {
    return { tone: "error", message: "Your admin approval session could not be verified. Sign in again before retrying.", reload: false };
  }
  if (error.status === 403) {
    return { tone: "error", message: "This admin session is not authorized to make this decision.", reload: false };
  }
  if (error.status === 404 || error.code === "proposal_not_found") {
    return { tone: "error", message: "This proposal no longer exists. Nothing was approved. Reload the proposal or return to the review queue.", reload: true };
  }
  if (error.code && STALE_CODES.has(error.code)) {
    return { tone: "error", message: "This proposal changed after the page was loaded. Nothing was approved. Reload the proposal and review the current evidence.", reload: true };
  }
  if (error.status === 400 || error.code === "selected_alternative_not_in_group") {
    return { tone: "error", message: "The selected printing is not valid for this proposal. Nothing was approved. Reload the proposal before continuing.", reload: true };
  }
  if (error.code && REFUSAL_CODES.has(error.code)) {
    return { tone: "error", message: `${safeBackendReason(error.message)} Nothing was approved.`, reload: false };
  }
  if (error.status === 422) {
    return { tone: "error", message: `The approval request did not pass validation. ${validationSummary(error)} Nothing was approved.`, reload: false };
  }
  if (error.uncertain || error.status === 0 || error.status >= 500) {
    return {
      tone: "warning",
      message: "The approval result is uncertain. Reload the proposal and review its current state before trying again. Nothing will be resent automatically.",
      reload: true,
    };
  }
  return { tone: "error", message: `${safeBackendReason(error.message)} Nothing was approved.`, reload: false };
}

function validationSummary(error: ProposalApprovalError): string {
  const detail = error.payload?.detail;
  if (!Array.isArray(detail)) return "Review the displayed proposal values.";
  const messages = detail.flatMap((entry) => typeof entry.msg === "string" ? [entry.msg] : []);
  return messages.length ? messages.join(" ") : "Review the displayed proposal values.";
}

function safeBackendReason(message: string): string {
  const normalized = message.trim();
  return normalized && normalized.length <= 500 ? normalized : "The backend refused this approval.";
}
