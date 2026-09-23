"use client";

import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/Badge";
import { resolveCardImageUrl } from "@/lib/cardImage";
import type {
  ProposalReviewCandidateSummary,
  ProposalReviewJsonValue,
  ProposalReviewPrint,
  ProposalReviewReleaseContext,
} from "@/lib/proposalReview";

const RESOLUTION_LABELS: Record<string, string> = {
  exact: "Exact proposal",
  ambiguous: "Ambiguous — multiple printings",
  unresolved_identity: "Identity unresolved",
  release_unresolved: "Release unresolved",
  conflict: "Conflict",
  stale: "Stale",
  superseded: "Superseded",
};

const RESOLUTION_STYLES: Record<string, string> = {
  exact: "bg-accent-teal/15 text-accent-teal-hover ring-accent-teal/30",
  ambiguous: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  unresolved_identity: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  release_unresolved: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  conflict: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  stale: "bg-neutral-500/15 text-text-secondary ring-neutral-500/30",
  superseded: "bg-neutral-500/15 text-text-muted ring-neutral-500/30",
};

export function proposalResolutionLabel(status: string): string {
  return RESOLUTION_LABELS[status] ?? status.replaceAll("_", " ");
}

export function ProposalResolutionBadge({ status }: { status: string }) {
  return (
    <Badge
      label={proposalResolutionLabel(status)}
      className={`ring-1 ring-inset ${
        RESOLUTION_STYLES[status] ?? "bg-neutral-500/15 text-text-secondary ring-neutral-500/30"
      }`}
    />
  );
}

export function ProposalSourceBadge({ source }: { source: string }) {
  const label = source.toLowerCase() === "yuyutei" ? "Yuyu" : source.toUpperCase();
  return (
    <Badge
      label={label}
      className="bg-bg-elevated text-text-secondary ring-1 ring-inset ring-border-strong"
    />
  );
}

export function ProposalReviewStatusBadge({ status }: { status: string }) {
  return (
    <Badge
      label={`Review: ${status.replaceAll("_", " ")}`}
      className="bg-neutral-500/15 text-text-secondary ring-1 ring-inset ring-neutral-500/30"
    />
  );
}

export function candidateDisplayName(candidate: ProposalReviewCandidateSummary): string {
  return (
    candidate.snkrdunk?.title ??
    candidate.yuyutei?.name_jp ??
    candidate.source_native_identity ??
    `Candidate ${candidate.candidate_id}`
  );
}

export function releaseDisplayName(release: ProposalReviewReleaseContext | null): string {
  if (!release) return "No authoritative release";
  return [release.official_code, release.display_name].filter(Boolean).join(" — ");
}

export function ProposalArtwork({
  print,
  alt,
  size = "queue",
}: {
  print: ProposalReviewPrint | null;
  alt: string;
  size?: "queue" | "detail";
}) {
  const [failed, setFailed] = useState(false);
  const displayImage = print?.display_image;
  // Proposal review never hotlinks a marketplace image merely because the
  // display-image selector found one. Only an owned mirror or first-party
  // Bandai evidence may be shown automatically; otherwise the canonical
  // official asset is the safe fallback. Bandai itself requires the existing
  // same-origin image proxy because its CORP header blocks direct embedding.
  const safeDisplayUrl =
    displayImage?.owned_asset_selected || displayImage?.source === "bandai"
      ? displayImage.url
      : null;
  const source = resolveCardImageUrl(safeDisplayUrl ?? print?.canonical_image_url ?? null);
  const showImage = Boolean(source && !failed && !print?.image_missing);
  const frameClass =
    size === "detail" ? "aspect-[63/88] w-full max-w-80 p-1.5" : "h-28 w-20";

  return (
    <div
      className={`${frameClass} flex shrink-0 items-center justify-center overflow-hidden rounded-panel border border-border-default bg-bg-page`}
    >
      {showImage ? (
        // Candidate and non-owned marketplace image URLs are deliberately
        // never passed here.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={source!}
          alt={alt}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="px-2 text-center text-[11px] leading-4 text-text-muted">
          Artwork unavailable
        </div>
      )}
    </div>
  );
}

export function ReadOnlyNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`rounded-control border border-sky-500/25 bg-sky-500/10 text-sky-200 ${
        compact ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm"
      }`}
    >
      Approval is available only from an eligible proposal detail page. Queue rows remain read-only.
    </div>
  );
}

export function ExternalSourceLink({ href, label = "Open source listing" }: { href: string; label?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1 text-xs font-medium text-sky-300 underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60"
    >
      {label} <span aria-hidden="true">↗</span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

export function KeyValueGrid({ children }: { children: ReactNode }) {
  return <dl className="grid gap-x-5 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">{children}</dl>;
}

export function KeyValue({ label, children, technical = false }: { label: string; children: ReactNode; technical?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className={`mt-0.5 min-w-0 text-text-primary ${technical ? "mono [overflow-wrap:anywhere]" : "break-words"}`}>{children ?? "—"}</dd>
    </div>
  );
}

export function EvidenceList({ values, empty = "None recorded" }: { values: ProposalReviewJsonValue[]; empty?: string }) {
  if (values.length === 0) return <p className="text-sm text-text-muted">{empty}</p>;
  return (
    <ul className="space-y-1.5 text-sm text-text-secondary">
      {values.map((value, index) => (
        <li key={index} className="flex gap-2">
          <span aria-hidden="true" className="text-text-faint">•</span>
          <span className="min-w-0 break-words">{jsonValueText(value)}</span>
        </li>
      ))}
    </ul>
  );
}

export function jsonValueText(value: ProposalReviewJsonValue): string {
  if (value === null) return "Not present";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function TechnicalJson({
  label,
  value,
}: {
  label: string;
  value: ProposalReviewJsonValue | Record<string, ProposalReviewJsonValue>;
}) {
  return (
    <details className="rounded-control border border-border-muted bg-bg-page px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60">
        {label}
      </summary>
      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words text-[11px] text-text-muted">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
