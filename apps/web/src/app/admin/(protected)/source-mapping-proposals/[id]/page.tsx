"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AdminBreadcrumbs, AdminPageHeader, AdminPageShell, AdminSection, AdminStatusBadge } from "@/components/admin/AdminPage";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { AdminAuthRequiredError, AdminNotFoundError } from "@/lib/api";
import { formatDateTime, formatJpy } from "@/lib/format";
import {
  fetchProposalReviewGroup,
  type ProposalReviewGroupDetail,
  type ProposalReviewJsonValue,
} from "@/lib/proposalReview";
import { safeProposalReviewReturnTo } from "@/lib/proposalReviewUrl";

import {
  EvidenceList,
  ExternalSourceLink,
  KeyValue,
  KeyValueGrid,
  ProposalResolutionBadge,
  ProposalReviewStatusBadge,
  ProposalSourceBadge,
  TechnicalJson,
  candidateDisplayName,
  jsonValueText,
  releaseDisplayName,
} from "../ProposalReviewComponents";
import { AlternativeCard } from "./AlternativeCard";
import { ExactProposalApprovalPanel } from "./ExactProposalApprovalPanel";

export default function ProposalReviewDetailPage() {
  return (
    <Suspense fallback={<DetailShell><LoadingState>Loading proposal evidence…</LoadingState></DetailShell>}>
      <ProposalReviewDetailPageInner />
    </Suspense>
  );
}

function DetailShell({ children }: { children: ReactNode }) {
  return <AdminPageShell>{children}</AdminPageShell>;
}

function ProposalReviewDetailPageInner() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const id = Number(params.id);
  const invalidId = !Number.isSafeInteger(id) || id <= 0;
  const returnTo = safeProposalReviewReturnTo(searchParams.get("returnTo"));
  const [proposal, setProposal] = useState<ProposalReviewGroupDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "not-found">("loading");
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [reloadRevision, setReloadRevision] = useState(0);
  const silentReloadRef = useRef(false);

  useEffect(() => {
    if (invalidId) return;
    const controller = new AbortController();
    if (silentReloadRef.current) silentReloadRef.current = false;
    else {
      queueMicrotask(() => {
        if (!controller.signal.aborted) setStatus("loading");
      });
    }
    fetchProposalReviewGroup(id, controller.signal)
      .then((result) => {
        setProposal(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else if (err instanceof AdminNotFoundError) setStatus("not-found");
        else {
          setError(err instanceof Error ? err.message : "Failed to load proposal evidence.");
          setStatus("error");
        }
      });
    return () => controller.abort();
  }, [id, invalidId, reloadRevision]);

  if (unauthorized) return <DetailShell><AdminSessionExpired /></DetailShell>;
  if (status === "loading") return <DetailShell><LoadingState>Loading proposal evidence…</LoadingState></DetailShell>;
  if (invalidId || status === "not-found") {
    return (
      <DetailShell>
        <ErrorState action={<Link href={returnTo} className="underline">Return to Proposal Review</Link>}>
          Proposal #{Number.isFinite(id) ? id : params.id} was not found.
        </ErrorState>
      </DetailShell>
    );
  }
  if (status === "error" || !proposal) {
    return <DetailShell><ErrorState>{error || "Failed to load proposal evidence."}</ErrorState></DetailShell>;
  }

  return (
    <DetailShell>
      <AdminBreadcrumbs items={[{ label: "Proposal Review", href: returnTo }, { label: `Proposal #${proposal.id}` }]} />
      <AdminPageHeader
        title={`Proposal #${proposal.id}`}
        description="Complete persisted resolver and exact-print evidence. Approval is available only after deliberate review of an eligible exact proposal."
        actions={<AdminStatusBadge>Detail review</AdminStatusBadge>}
      />

      <div className="mt-5 space-y-5">
        <DetailSection title="Proposal">
          <div className="mb-4 flex flex-wrap gap-2">
            <ProposalSourceBadge source={proposal.source_name} />
            <ProposalResolutionBadge status={proposal.resolution_status} />
            <ProposalReviewStatusBadge status={proposal.review_status} />
          </div>
          <KeyValueGrid>
            <KeyValue label="Card">{proposal.name_en ?? proposal.name_jp ?? "Canonical identity unresolved"}</KeyValue>
            <KeyValue label="Card code">{proposal.card_code ?? proposal.candidate.detected_card_code ?? "Not established"}</KeyValue>
            <KeyValue label="Authoritative release">{releaseDisplayName(proposal.release)}</KeyValue>
            <KeyValue label="Proposal ID">{proposal.id}</KeyValue>
            <KeyValue label="Resolver version">{proposal.resolver_version}</KeyValue>
            <KeyValue label="Created">{formatDateTime(proposal.created_at)}</KeyValue>
            <KeyValue label="Updated">{formatDateTime(proposal.updated_at)}</KeyValue>
            <KeyValue label="Superseded">{proposal.superseded_at ? formatDateTime(proposal.superseded_at) : "No"}</KeyValue>
            <KeyValue label="Resulting mapping">{proposal.resulting_source_card_mapping_id ? `Mapping #${proposal.resulting_source_card_mapping_id}` : "None"}</KeyValue>
          </KeyValueGrid>
          <div className="mt-4"><ExternalSourceLink href={proposal.source_url} /></div>
        </DetailSection>

        <DetailSection title="Source evidence">
          <KeyValueGrid>
            <KeyValue label="Candidate">{candidateDisplayName(proposal.candidate)}</KeyValue>
            <KeyValue label="Candidate type / ID">{proposal.candidate.candidate_type} #{proposal.candidate.candidate_id}</KeyValue>
            <KeyValue label="Source-native identity">{proposal.candidate.source_native_identity}</KeyValue>
            <KeyValue label="Normalized title">{proposal.candidate.normalized_title ?? "Not stored"}</KeyValue>
            <KeyValue label="Candidate match state">{proposal.candidate.match_status ?? "Not stored"}</KeyValue>
            <KeyValue label="Detected card code">{proposal.candidate.detected_card_code ?? "Not detected"}</KeyValue>
            <KeyValue label="Detected rarity">{proposal.candidate.detected_rarity ?? "Not detected"}</KeyValue>
            <KeyValue label="Candidate price">{formatJpy(proposal.candidate.price_jpy)}</KeyValue>
            <KeyValue label="Availability">{proposal.candidate.yuyutei?.availability ?? "Not stored"}</KeyValue>
            <KeyValue label="Listing count">{proposal.candidate.snkrdunk?.listing_count ?? "Not stored"}</KeyValue>
            <KeyValue label="Condition">{proposal.candidate.snkrdunk?.condition_label ?? "Not stored"}</KeyValue>
            <KeyValue label="Detected set">{proposal.candidate.snkrdunk?.detected_set_code ?? proposal.candidate.yuyutei?.set_slug ?? "Not detected"}</KeyValue>
            <KeyValue label="Detected variant">{proposal.candidate.snkrdunk?.detected_variant ?? "Not detected"}</KeyValue>
            <KeyValue label="Yuyu product ID">{proposal.candidate.yuyutei?.product_id ?? "Not applicable"}</KeyValue>
            <KeyValue label="Candidate record">{proposal.candidate.candidate_missing ? "Missing" : "Present"}</KeyValue>
          </KeyValueGrid>
          <div className="mt-4 rounded-control border border-border-muted bg-bg-page p-3 text-sm text-text-secondary">
            {proposal.candidate.image_url ? (
              <>
                Stored candidate artwork URL is present but is not loaded automatically.{" "}
                <a href={proposal.candidate.image_url} target="_blank" rel="noreferrer noopener" className="text-accent-teal-hover hover:underline">
                  Open stored candidate image <span aria-hidden="true">↗</span><span className="sr-only"> (opens in a new tab)</span>
                </a>
              </>
            ) : "Candidate artwork is missing."}
          </div>
          {proposal.candidate.raw_listing_text && <div className="mt-4 rounded-control border border-border-muted bg-bg-page p-3 text-sm whitespace-pre-wrap break-words text-text-secondary">{proposal.candidate.raw_listing_text}</div>}
          {proposal.candidate.discovery_run ? (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-medium text-text-primary">Discovery provenance</h3>
              <KeyValueGrid>
                <KeyValue label="Run ID">{proposal.candidate.discovery_run.id}</KeyValue>
                <KeyValue label="Run source">{proposal.candidate.discovery_run.source}</KeyValue>
                <KeyValue label="Run status">{proposal.candidate.discovery_run.status}</KeyValue>
                <KeyValue label="Started">{formatDateTime(proposal.candidate.discovery_run.started_at)}</KeyValue>
                <KeyValue label="Finished">{formatDateTime(proposal.candidate.discovery_run.finished_at)}</KeyValue>
              </KeyValueGrid>
              <div className="mt-3"><TechnicalJson label="Discovery provenance details" value={proposal.candidate.discovery_run.provenance} /></div>
            </div>
          ) : <p className="mt-4 text-sm text-text-muted">No discovery-run provenance is available.</p>}
          <div className="mt-4"><ExternalSourceLink href={proposal.candidate.source_url} label="Open candidate source listing" /></div>
        </DetailSection>

        <DetailSection title="Canonical identity">
          {proposal.canonical_card ? (
            <KeyValueGrid>
              <KeyValue label="Canonical card ID">{proposal.canonical_card.id}</KeyValue>
              <KeyValue label="Card code">{proposal.canonical_card.card_code}</KeyValue>
              <KeyValue label="English name">{proposal.canonical_card.name_en ?? "Not stored"}</KeyValue>
              <KeyValue label="Japanese name">{proposal.canonical_card.name_jp ?? "Not stored"}</KeyValue>
              <KeyValue label="Card type">{proposal.canonical_card.card_type ?? "Not stored"}</KeyValue>
              <KeyValue label="Canonical rarity">{proposal.canonical_card.canonical_rarity ?? "Not stored"}</KeyValue>
            </KeyValueGrid>
          ) : <p className="text-sm text-rose-300">No canonical card family was established.</p>}
        </DetailSection>

        <DetailSection title="Authoritative release">
          {proposal.release ? (
            <>
              <KeyValueGrid>
                <KeyValue label="Release product ID">{proposal.release.id}</KeyValue>
                <KeyValue label="Official code">{proposal.release.official_code ?? "Uncoded product"}</KeyValue>
                <KeyValue label="Display name">{proposal.release.display_name}</KeyValue>
                <KeyValue label="Source catalogue">{proposal.release.source_catalogue}</KeyValue>
                <KeyValue label="Source series">{proposal.release.source_series_id}</KeyValue>
                <KeyValue label="Verification status">{proposal.release.verification_status}</KeyValue>
              </KeyValueGrid>
              <p className="mt-4 rounded-control border border-violet-500/25 bg-violet-500/10 p-3 text-sm text-violet-200">{proposal.release.membership_explanation}</p>
              <p className="mt-2 text-xs text-text-muted">Release dates are not available in the catalogue yet; deterministic catalogue order is not authoritative chronology.</p>
            </>
          ) : (
            <div className="rounded-control border border-violet-500/25 bg-violet-500/10 p-3 text-sm text-violet-200">
              No authoritative ReleaseProduct was established. A release is not inferred from the card-code prefix or source title.
            </div>
          )}
        </DetailSection>

        <DetailSection title={`Proposed printings (${proposal.alternatives.length})`}>
          {proposal.alternatives.length > 0 ? (
            <div className="grid min-w-0 grid-cols-1 gap-5" data-proposed-printings="">
              {proposal.alternatives.map((alternative) => <AlternativeCard key={alternative.alternative_id} alternative={alternative} />)}
            </div>
          ) : <p className="text-sm text-text-muted">No exact-print alternatives were established.</p>}
        </DetailSection>

        <DetailSection title="Resolver reasoning">
          <div className="grid min-w-0 gap-5 lg:grid-cols-2">
            <div className="min-w-0"><h3 className="mb-2 text-sm font-medium text-text-primary">Resolution reasons</h3><EvidenceList values={proposal.resolution_reasons} /></div>
            <div className="min-w-0">
              <h3 className="mb-2 text-sm font-medium text-text-primary">Evidence summary</h3>
              <dl className="space-y-2">
                {Object.entries(proposal.evidence_summary).map(([key, value]) => (
                  <div key={key} className="grid min-w-0 grid-cols-[minmax(8rem,0.4fr)_minmax(0,1fr)] gap-3 border-b border-border-muted pb-2 text-sm">
                    <dt className="text-text-muted">{key.replaceAll("_", " ")}</dt><dd className="min-w-0 [overflow-wrap:anywhere] text-text-primary">{jsonValueText(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
          <KeyValueGrid>
            <KeyValue label="Evidence digest" technical>{proposal.evidence_digest}</KeyValue>
            <KeyValue label="Resolver version">{proposal.resolver_version}</KeyValue>
          </KeyValueGrid>
          <div className="mt-4 space-y-2">
            <TechnicalJson label="Raw evidence summary" value={proposal.evidence_summary} />
            <TechnicalJson label="Stored candidate evidence" value={proposal.candidate.stored_evidence} />
            {proposal.candidate.match_explanation && <TechnicalJson label="Candidate match explanation" value={proposal.candidate.match_explanation} />}
            {proposal.candidate.ambiguous_matches && <TechnicalJson label="Stored ambiguous matches" value={proposal.candidate.ambiguous_matches} />}
          </div>
        </DetailSection>

        <ExactProposalApprovalPanel
          proposal={proposal}
          onReload={(options) => {
            silentReloadRef.current = options?.silent === true;
            setReloadRevision((revision) => revision + 1);
          }}
        />

        <details className="rounded-panel border border-border-default bg-bg-surface p-4">
          <summary className="cursor-pointer text-base font-semibold text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60">Legacy compatibility metadata</summary>
          <p className="mt-3 text-sm text-amber-200">This metadata is retained for older collection and compatibility paths. It is not authoritative pricing identity.</p>
          <p className="mt-2 text-sm text-text-secondary">{proposal.compatibility.role}</p>
          <KeyValueGrid>
            <KeyValue label="Candidate matched card ID">{proposal.compatibility.candidate_matched_card_id ?? "None"}</KeyValue>
            <KeyValue label="Candidate best-match card ID">{proposal.compatibility.candidate_best_match_card_id ?? "None"}</KeyValue>
            <KeyValue label="Resulting mapping card ID">{proposal.compatibility.resulting_mapping_card_id ?? "None"}</KeyValue>
          </KeyValueGrid>
          {proposal.compatibility.legacy_cards.length > 0 && <div className="mt-3"><TechnicalJson label="Legacy Card records" value={proposal.compatibility.legacy_cards as unknown as ProposalReviewJsonValue} /></div>}
        </details>

        <DetailSection title="Historical state">
          <KeyValueGrid>
            <KeyValue label="Superseded at">{proposal.superseded_at ? formatDateTime(proposal.superseded_at) : "Current proposal"}</KeyValue>
            <KeyValue label="Resulting mapping">{proposal.resulting_mapping ? "Linked" : "None"}</KeyValue>
            <KeyValue label="Review status">{proposal.review_status}</KeyValue>
          </KeyValueGrid>
          <div className="mt-4 space-y-2">
            <TechnicalJson label="Historical metadata" value={proposal.historical_state} />
            {proposal.resulting_mapping && <TechnicalJson label="Resulting mapping linkage" value={proposal.resulting_mapping} />}
          </div>
        </DetailSection>
      </div>
      <div className="mt-6"><Link href={returnTo} className="rounded-control border border-border-default px-3 py-2 text-sm font-medium text-accent-teal-hover hover:border-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60">← Return to filtered queue</Link></div>
    </DetailShell>
  );
}

const DetailSection = AdminSection;
