"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { FILTER_INPUT_CLASS, FILTER_LABEL_CLASS, FilterBar } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import { AdminAuthRequiredError } from "@/lib/api";
import { formatDateTime, formatJpy } from "@/lib/format";
import {
  fetchProposalReviewGroups,
  fetchProposalReviewReleases,
  fetchProposalReviewSummary,
  type ProposalReviewGroup,
  type ProposalReviewGroupList,
  type ProposalReviewRelease,
  type ProposalReviewSummary,
} from "@/lib/proposalReview";
import {
  PROPOSAL_REVIEW_LIMITS,
  parseProposalReviewQueueState,
  proposalReviewQueueHref,
  proposalReviewStateParams,
  type ProposalReviewQueueState,
} from "@/lib/proposalReviewUrl";

import {
  ExternalSourceLink,
  ProposalArtwork,
  ProposalResolutionBadge,
  ProposalReviewStatusBadge,
  ProposalSourceBadge,
  ReadOnlyNotice,
  candidateDisplayName,
  releaseDisplayName,
} from "./ProposalReviewComponents";

const SOURCE_FILTERS = [
  { value: "", label: "All" },
  { value: "yuyutei", label: "Yuyu" },
  { value: "snkrdunk", label: "SNKRDUNK" },
] as const;

const RESOLUTION_FILTERS = [
  { value: "", label: "All" },
  { value: "exact", label: "Exact" },
  { value: "ambiguous", label: "Ambiguous" },
  { value: "unresolved_identity", label: "Identity unresolved" },
  { value: "release_unresolved", label: "Release unresolved" },
] as const;

const SORT_OPTIONS = [
  ["default", "Default queue order"],
  ["id_asc", "Proposal ID — ascending"],
  ["id_desc", "Proposal ID — descending"],
  ["created_newest", "Newest created"],
  ["created_oldest", "Oldest created"],
  ["release_newest", "Release order — newest fallback"],
  ["release_oldest", "Release order — oldest fallback"],
  ["exact_first", "Exact proposals first"],
  ["ambiguous_first", "Ambiguous proposals first"],
  ["source", "Source"],
  ["card_code", "Card code"],
] as const;

export default function ProposalReviewPage() {
  return (
    <Suspense fallback={<ProposalReviewShell><LoadingState>Loading proposal review…</LoadingState></ProposalReviewShell>}>
      <ProposalReviewPageInner />
    </Suspense>
  );
}

function ProposalReviewShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

function ProposalReviewPageInner() {
  const router = useRouter();
  const pathname = usePathname() || "/admin/source-mapping-proposals";
  const searchParams = useSearchParams();
  const searchKey = searchParams.toString();
  const [queue, setQueue] = useState<ProposalReviewQueueState>(() =>
    parseProposalReviewQueueState(new URLSearchParams(searchKey)),
  );
  const [searchDraft, setSearchDraft] = useState(() =>
    parseProposalReviewQueueState(new URLSearchParams(searchKey)).q,
  );
  const [summary, setSummary] = useState<ProposalReviewSummary | null>(null);
  const [releases, setReleases] = useState<ProposalReviewRelease[]>([]);
  const [data, setData] = useState<ProposalReviewGroupList | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);

  // Browser back/forward is authoritative. Invalid values are replaced by a
  // canonical safe URL, so refreshes and shared links reproduce the same view.
  useEffect(() => {
    const parsed = parseProposalReviewQueueState(new URLSearchParams(searchKey));
    const canonical = proposalReviewStateParams(parsed).toString();
    if (canonical !== searchKey) {
      router.replace(`${pathname}${canonical ? `?${canonical}` : ""}`, { scroll: false });
    }
    const sync = window.setTimeout(() => {
      setQueue((current) =>
        proposalReviewStateParams(current).toString() === canonical ? current : parsed,
      );
      setSearchDraft(parsed.q);
    }, 0);
    return () => window.clearTimeout(sync);
  }, [pathname, router, searchKey]);

  const updateQueue = useCallback(
    (patch: Partial<ProposalReviewQueueState>, resetPage = true) => {
      setQueue((current) => {
        const next = { ...current, ...patch, ...(resetPage ? { page: 1 } : {}) };
        router.replace(proposalReviewQueueHref(next), { scroll: false });
        return next;
      });
    },
    [router],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (searchDraft !== queue.q) updateQueue({ q: searchDraft });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [queue.q, searchDraft, updateQueue]);

  useEffect(() => {
    let active = true;
    Promise.all([fetchProposalReviewSummary(), fetchProposalReviewReleases()])
      .then(([summaryResult, releaseResult]) => {
        if (!active) return;
        setSummary(summaryResult);
        setReleases(releaseResult.items);
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else setError(err instanceof Error ? err.message : "Failed to load proposal summary.");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        setStatus("loading");
        setError(null);
      }
    });
    fetchProposalReviewGroups({
      source: queue.source || undefined,
      release_product_id: queue.release ? Number(queue.release) : undefined,
      unresolved_release: queue.unresolvedRelease || undefined,
      resolution_status: queue.resolution || undefined,
      review_status: queue.reviewStatus || undefined,
      card_code: queue.cardCode || undefined,
      candidate_id: queue.candidateId ? Number(queue.candidateId) : undefined,
      proposal_group_id: queue.proposalId ? Number(queue.proposalId) : undefined,
      has_candidate_image: queue.hasImage ? queue.hasImage === "true" : undefined,
      has_recommended_alternative: queue.hasRecommended
        ? queue.hasRecommended === "true"
        : undefined,
      include_superseded: queue.includeSuperseded || undefined,
      q: queue.q || undefined,
      sort: queue.sort,
      limit: queue.limit,
      offset: (queue.page - 1) * queue.limit,
      signal: controller.signal,
    })
      .then((result) => {
        setData(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
        else {
          setError(err instanceof Error ? err.message : "Failed to load proposals.");
          setStatus("error");
        }
      });
    return () => controller.abort();
  }, [queue]);

  if (unauthorized) {
    return (
      <ProposalReviewShell>
        <AdminSessionExpired />
      </ProposalReviewShell>
    );
  }

  const currentReturnTo = proposalReviewQueueHref(queue);
  const unresolvedRelease = releases.find((release) => release.release_product_id === null);
  const normalReleases = releases.filter((release) => release.release_product_id !== null);

  return (
    <ProposalReviewShell>
      <PageHeader
        title="Proposal Review"
        description="Review persisted source-listing evidence against exact physical printings. Nothing on this page approves a mapping."
        actions={
          <span className="rounded-control border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-xs font-medium text-sky-200">
            Read-only queue
          </span>
        }
      />
      <ReadOnlyNotice />

      <section aria-labelledby="queue-summary-heading" className="mt-4">
        <h2 id="queue-summary-heading" className="sr-only">Queue summary</h2>
        <StatGrid>
          <StatCard label="Total proposals" value={summary?.total_current_groups.toLocaleString() ?? "—"} />
          <StatCard label="Exact" value={summary?.by_resolution.exact.toLocaleString() ?? "—"} hint="Human review still required" />
          <StatCard label="Ambiguous" value={summary?.by_resolution.ambiguous.toLocaleString() ?? "—"} />
          <StatCard label="Identity unresolved" value={summary?.by_resolution.unresolved_identity.toLocaleString() ?? "—"} />
          <StatCard label="Release unresolved" value={summary?.by_resolution.release_unresolved.toLocaleString() ?? "—"} />
          <StatCard label="Yuyu" value={summary?.by_source.yuyutei?.total_current_groups.toLocaleString() ?? "—"} />
          <StatCard label="SNKRDUNK" value={summary?.by_source.snkrdunk?.total_current_groups.toLocaleString() ?? "—"} />
          <StatCard label="Multiple alternatives" value={summary?.groups_with_multiple_alternatives.toLocaleString() ?? "—"} />
        </StatGrid>
      </section>

      <section aria-labelledby="quick-filters-heading" className="mt-5 space-y-3">
        <h2 id="quick-filters-heading" className="text-sm font-semibold text-text-primary">Quick filters</h2>
        <QuickFilterRow
          label="Source"
          options={SOURCE_FILTERS.map((option) => ({
            ...option,
            count:
              option.value === ""
                ? summary?.total_current_groups
                : summary?.by_source[option.value]?.total_current_groups,
          }))}
          value={queue.source}
          onChange={(value) => updateQueue({ source: value as ProposalReviewQueueState["source"] })}
        />
        <QuickFilterRow
          label="Resolution"
          options={RESOLUTION_FILTERS.map((option) => ({
            ...option,
            count:
              option.value === ""
                ? summary?.total_current_groups
                : summary?.by_resolution[option.value as keyof typeof summary.by_resolution],
          }))}
          value={queue.resolution}
          onChange={(value) => updateQueue({ resolution: value as ProposalReviewQueueState["resolution"] })}
        />
      </section>

      <section aria-labelledby="detailed-filters-heading" className="mt-5 rounded-panel border border-border-default bg-bg-surface p-3">
        <h2 id="detailed-filters-heading" className="mb-3 text-sm font-semibold text-text-primary">Detailed filters</h2>
        <FilterBar>
          <label className={FILTER_LABEL_CLASS}>
            Search
            <input
              aria-label="Search proposals"
              type="search"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Card, name, listing identity…"
              className={`${FILTER_INPUT_CLASS} w-56`}
            />
          </label>
          <label className={FILTER_LABEL_CLASS}>
            Release
            <select
              aria-label="Authoritative release"
              value={queue.unresolvedRelease ? "unresolved" : queue.release}
              onChange={(event) => {
                const unresolved = event.target.value === "unresolved";
                updateQueue({ unresolvedRelease: unresolved, release: unresolved ? "" : event.target.value });
              }}
              className={`${FILTER_INPUT_CLASS} max-w-80`}
            >
              <option value="">All releases</option>
              <option value="unresolved">
                Unresolved release ({unresolvedRelease?.pending_proposal_groups ?? 0})
              </option>
              {normalReleases.map((release) => (
                <option key={release.release_product_id} value={release.release_product_id ?? ""}>
                  {release.official_code ? `${release.official_code} — ` : ""}{release.display_name} ({release.pending_proposal_groups})
                </option>
              ))}
            </select>
          </label>
          <label className={FILTER_LABEL_CLASS}>
            Review status
            <select
              aria-label="Review status"
              value={queue.reviewStatus}
              onChange={(event) => updateQueue({ reviewStatus: event.target.value as ProposalReviewQueueState["reviewStatus"] })}
              className={FILTER_INPUT_CLASS}
            >
              <option value="">All review states</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
          <LabeledTextFilter label="Card code" value={queue.cardCode} onChange={(cardCode) => updateQueue({ cardCode })} />
          <LabeledTextFilter label="Candidate ID" inputMode="numeric" value={queue.candidateId} onChange={(candidateId) => updateQueue({ candidateId: candidateId.replace(/\D/g, "") })} />
          <LabeledTextFilter label="Proposal ID" inputMode="numeric" value={queue.proposalId} onChange={(proposalId) => updateQueue({ proposalId: proposalId.replace(/\D/g, "") })} />
          <label className={FILTER_LABEL_CLASS}>
            Candidate artwork
            <select aria-label="Candidate artwork" value={queue.hasImage} onChange={(event) => updateQueue({ hasImage: event.target.value as ProposalReviewQueueState["hasImage"] })} className={FILTER_INPUT_CLASS}>
              <option value="">Any</option><option value="true">Present</option><option value="false">Missing</option>
            </select>
          </label>
          <label className={FILTER_LABEL_CLASS}>
            Recommended print
            <select aria-label="Recommended print" value={queue.hasRecommended} onChange={(event) => updateQueue({ hasRecommended: event.target.value as ProposalReviewQueueState["hasRecommended"] })} className={FILTER_INPUT_CLASS}>
              <option value="">Any</option><option value="true">Present</option><option value="false">Missing</option>
            </select>
          </label>
          <label className={`${FILTER_LABEL_CLASS} rounded-control border border-border-default px-2 py-1`}>
            <input type="checkbox" checked={queue.includeSuperseded} onChange={(event) => updateQueue({ includeSuperseded: event.target.checked })} />
            Include superseded
          </label>
          <label className={FILTER_LABEL_CLASS}>
            Sort
            <select aria-label="Sort proposals" value={queue.sort} onChange={(event) => updateQueue({ sort: event.target.value as ProposalReviewQueueState["sort"] })} className={FILTER_INPUT_CLASS}>
              {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className={FILTER_LABEL_CLASS}>
            Page size
            <select aria-label="Page size" value={queue.limit} onChange={(event) => updateQueue({ limit: Number(event.target.value) as ProposalReviewQueueState["limit"] })} className={FILTER_INPUT_CLASS}>
              {PROPOSAL_REVIEW_LIMITS.map((limit) => <option key={limit} value={limit}>{limit}</option>)}
            </select>
          </label>
        </FilterBar>
        <p className="text-[11px] text-text-muted">
          Release dates are not available in the catalogue yet; this list uses the current deterministic catalogue order.
        </p>
      </section>

      <section aria-labelledby="queue-results-heading" className="mt-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 id="queue-results-heading" className="text-sm font-semibold text-text-primary">Queue results</h2>
          {status === "loading" && data && <span role="status" className="text-xs text-text-muted">Updating results…</span>}
        </div>
        {status === "loading" && !data && <LoadingState>Loading persisted proposals…</LoadingState>}
        {status === "error" && <ErrorState>{error || "Failed to load proposal review queue."}</ErrorState>}
        {data && data.items.length === 0 && status !== "error" && <EmptyState>No proposals match these filters.</EmptyState>}
        {data && data.items.length > 0 && (
          <>
            <ProposalDesktopTable items={data.items} returnTo={currentReturnTo} />
            <ProposalMobileCards items={data.items} returnTo={currentReturnTo} />
            <div className="mt-4">
              <PaginationControls
                offset={data.pagination.offset}
                limit={data.pagination.limit}
                total={data.pagination.total}
                onOffsetChange={(offset) => updateQueue({ page: Math.floor(offset / queue.limit) + 1 }, false)}
              />
            </div>
          </>
        )}
      </section>

      {releases.length > 0 && (
        <details className="mt-6 rounded-panel border border-border-default bg-bg-surface p-3">
          <summary className="cursor-pointer text-sm font-semibold text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60">
            Release queue summary ({releases.length} catalogue buckets)
          </summary>
          <p className="mt-2 text-xs text-text-muted">Catalogue order is deterministic, not authoritative chronology.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {releases.map((release) => (
              <button
                type="button"
                key={release.release_product_id ?? "unresolved"}
                onClick={() => updateQueue({ release: release.release_product_id ? String(release.release_product_id) : "", unresolvedRelease: release.release_product_id === null })}
                className="rounded-control border border-border-muted bg-bg-page p-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60"
              >
                <span className="block text-xs font-medium text-text-primary">{release.official_code ? `${release.official_code} — ` : ""}{release.display_name}</span>
                <span className="text-[11px] text-text-muted">{release.pending_proposal_groups.toLocaleString()} pending · {release.alternatives.toLocaleString()} alternatives</span>
              </button>
            ))}
          </div>
        </details>
      )}
    </ProposalReviewShell>
  );
}

function QuickFilterRow({ label, options, value, onChange }: { label: string; options: { value: string; label: string; count?: number }[]; value: string; onChange: (value: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-20 text-xs font-medium text-text-secondary">{label}</span>
      {options.map((option) => (
        <button
          key={option.value || "all"}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`rounded-control border px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 ${value === option.value ? "border-accent-teal bg-accent-teal/15 text-text-primary" : "border-border-default bg-bg-surface text-text-secondary hover:border-border-strong"}`}
        >
          {option.label}{option.count !== undefined ? ` (${option.count.toLocaleString()})` : ""}
        </button>
      ))}
    </div>
  );
}

function LabeledTextFilter({ label, value, onChange, inputMode }: { label: string; value: string; onChange: (value: string) => void; inputMode?: "numeric" }) {
  return <label className={FILTER_LABEL_CLASS}>{label}<input aria-label={label} inputMode={inputMode} value={value} onChange={(event) => onChange(event.target.value)} className={`${FILTER_INPUT_CLASS} w-28`} /></label>;
}

function detailHref(item: ProposalReviewGroup, returnTo: string): string {
  return `/admin/source-mapping-proposals/${item.id}?returnTo=${encodeURIComponent(returnTo)}`;
}

function resolutionHint(item: ProposalReviewGroup): string {
  if (item.resolution_status === "exact") return "Human review still required.";
  if (item.resolution_status === "ambiguous") return "More evidence is needed to distinguish the possible printings.";
  if (item.resolution_status === "unresolved_identity") return "No canonical card family was established.";
  if (item.resolution_status === "release_unresolved") return "No authoritative ReleaseProduct was established; no release is inferred from the card code.";
  return "Inspect the complete resolver evidence before making a decision.";
}

function CandidateEvidence({ item }: { item: ProposalReviewGroup }) {
  const candidate = item.candidate;
  return (
    <div className="min-w-0 space-y-1 text-xs">
      <div className="font-medium text-text-primary">{candidateDisplayName(candidate)}</div>
      <div className="break-all text-text-muted">{item.canonical_source_listing_identity}</div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-text-secondary">
        <span>{formatJpy(candidate.price_jpy)}</span>
        {candidate.detected_card_code && <span>Detected {candidate.detected_card_code}</span>}
        {(candidate.snkrdunk?.detected_set_code ?? candidate.yuyutei?.set_slug) && (
          <span>Source product {candidate.snkrdunk?.detected_set_code ?? candidate.yuyutei?.set_slug}</span>
        )}
        {candidate.image_missing && <span className="text-amber-300">Candidate artwork missing</span>}
        {candidate.candidate_missing && <span className="text-rose-300">Candidate record missing</span>}
      </div>
      <ExternalSourceLink href={item.source_url} />
    </div>
  );
}

function CardIdentity({ item }: { item: ProposalReviewGroup }) {
  const name = item.name_en ?? item.name_jp ?? "Canonical identity unresolved";
  return (
    <div className="min-w-0">
      <div className="font-semibold text-text-primary">{name}</div>
      {item.name_en && item.name_jp && <div className="text-xs text-text-secondary">{item.name_jp}</div>}
      <div className="mono mt-1 text-xs text-text-muted">{item.card_code ?? item.candidate.detected_card_code ?? "No detected card code"}</div>
      <div className="mt-1 text-[11px] text-text-faint">Proposal #{item.id} · Candidate #{item.source_candidate_id}</div>
    </div>
  );
}

function ResolverContext({ item }: { item: ProposalReviewGroup }) {
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap gap-1.5"><ProposalResolutionBadge status={item.resolution_status} /><ProposalReviewStatusBadge status={item.review_status} /></div>
      <div className="font-medium text-text-primary">{releaseDisplayName(item.release)}</div>
      {item.recommended_print && (
        <div className="text-text-secondary">
          {[item.recommended_print.printing_label, item.recommended_print.special_print_label, item.recommended_print.official_rarity, item.recommended_print.official_asset_variant].filter(Boolean).join(" · ") || `Print #${item.recommended_print.card_print_id}`}
        </div>
      )}
      <p className="text-text-muted">{resolutionHint(item)}</p>
    </div>
  );
}

function EvidenceSummary({ item, returnTo }: { item: ProposalReviewGroup; returnTo: string }) {
  return (
    <div className="space-y-2 text-xs">
      <div className="font-medium text-text-primary">{item.alternative_count} {item.alternative_count === 1 ? "possible printing" : "possible printings"}</div>
      <div className="text-text-secondary">{item.recommended_alternative_count > 0 ? `${item.recommended_alternative_count} recommended print` : "No recommended print"}</div>
      <div className="text-text-muted">Created {formatDateTime(item.created_at)}</div>
      <Link href={detailHref(item, returnTo)} className="inline-flex rounded-control border border-border-default px-2 py-1 font-medium text-sky-300 hover:border-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60" aria-label={`Review evidence for proposal ${item.id}`}>Review evidence</Link>
    </div>
  );
}

function ProposalDesktopTable({ items, returnTo }: { items: ProposalReviewGroup[]; returnTo: string }) {
  return (
    <div className="hidden overflow-hidden rounded-panel border border-border-default md:block">
      <table className="data-table w-full table-fixed text-left text-xs">
        <thead><tr><th className="w-[31%]">Card identity</th><th className="w-[25%]">Source listing evidence</th><th className="w-[27%]">Resolver state and release</th><th className="w-[17%]">Alternatives</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <td><div className="flex gap-3"><ProposalArtwork print={item.recommended_print} alt={`${item.name_en ?? item.name_jp ?? item.card_code ?? "Card"} artwork`} /><div className="space-y-2"><div className="flex flex-wrap gap-1.5"><ProposalSourceBadge source={item.source_name} /></div><CardIdentity item={item} /></div></div></td>
              <td><CandidateEvidence item={item} /></td>
              <td><ResolverContext item={item} /></td>
              <td><EvidenceSummary item={item} returnTo={returnTo} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProposalMobileCards({ items, returnTo }: { items: ProposalReviewGroup[]; returnTo: string }) {
  return (
    <div className="space-y-3 md:hidden">
      {items.map((item) => (
        <article key={item.id} className="rounded-panel border border-border-default bg-bg-surface p-3">
          <div className="mb-3 flex flex-wrap gap-1.5"><ProposalSourceBadge source={item.source_name} /><ProposalResolutionBadge status={item.resolution_status} /></div>
          <div className="flex gap-3"><ProposalArtwork print={item.recommended_print} alt={`${item.name_en ?? item.name_jp ?? item.card_code ?? "Card"} artwork`} /><div className="min-w-0 flex-1"><CardIdentity item={item} /><div className="mt-2 text-xs font-medium text-text-primary">{releaseDisplayName(item.release)}</div><div className="mt-1 text-xs text-text-secondary">{formatJpy(item.candidate.price_jpy)} · {item.alternative_count} {item.alternative_count === 1 ? "printing" : "possible printings"}</div></div></div>
          <div className="mt-3 border-t border-border-muted pt-3"><CandidateEvidence item={item} /></div>
          <div className="mt-3 flex items-center justify-between gap-3"><span className="text-xs text-text-muted">{resolutionHint(item)}</span><Link href={detailHref(item, returnTo)} className="shrink-0 rounded-control border border-border-default px-2.5 py-1.5 text-xs font-medium text-sky-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60" aria-label={`Review evidence for proposal ${item.id}`}>Review evidence</Link></div>
        </article>
      ))}
    </div>
  );
}
