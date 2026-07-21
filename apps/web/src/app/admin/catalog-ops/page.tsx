"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  fetchCardDuplicates,
  fetchCatalogCoverage,
  fetchImportValidationReports,
  fetchMappingQuality,
  fetchPriceSourceHealth,
} from "@/lib/api";
import { formatPercent } from "@/lib/format";

const NOT_AVAILABLE = "not available";

interface CatalogOpsSummary {
  metadataCompletionPct: number | null;
  mappingCoveragePct: number | null;
  recentPriceCoveragePct: number | null;
  duplicateRiskCount: number | null;
  mappingQualityCriticalCount: number | null;
  priceSourceHealthWarningCount: number | null;
  latestValidationStatus: "valid" | "invalid" | "none" | null;
}

interface OpsCard {
  title: string;
  href: string;
  description: string;
}

const OPS_CARDS: OpsCard[] = [
  {
    title: "Card Catalog",
    href: "/admin/cards",
    description: "Import/export canonical cards.",
  },
  {
    title: "Import Validation",
    href: "/admin/import-validation",
    description: "Download templates and validate CSVs.",
  },
  {
    title: "Card Audit",
    href: "/admin/card-audit",
    description: "Catalog identity/data checks.",
  },
  {
    title: "Duplicate Review",
    href: "/admin/card-duplicates",
    description: "Merge duplicate canonical cards safely.",
  },
  {
    title: "Source Candidate Matching",
    href: "/admin/snkrdunk-candidates",
    description: "Review imported candidates and matching confidence.",
  },
  {
    title: "Source Mapping Quality",
    href: "/admin/source-mapping-quality",
    description: "Review low-confidence/stale/duplicate mappings.",
  },
  {
    title: "Catalog Coverage",
    href: "/admin/catalog-coverage",
    description: "Mapping, price, metadata, wishlist and collection coverage.",
  },
  {
    title: "Price Source Health",
    href: "/admin/price-source-health",
    description: "Source freshness, failed refreshes and missing prices.",
  },
  {
    title: "System Check",
    href: "/admin/system-check",
    description: "Overall health check.",
  },
];

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function formatCount(value: number | null): string {
  if (value === null) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-US").format(value);
}

function formatValidationStatus(status: CatalogOpsSummary["latestValidationStatus"]): string {
  if (status === null || status === "none") return NOT_AVAILABLE;
  return status;
}

export default function CatalogOpsPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [summary, setSummary] = useState<CatalogOpsSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");

    Promise.allSettled([
      fetchCatalogCoverage(),
      fetchPriceSourceHealth(),
      fetchMappingQuality({ limit: 1 }),
      fetchCardDuplicates({ limit: 1 }),
      fetchImportValidationReports({ limit: 1 }),
    ]).then((results) => {
      if (cancelled) return;

      const authError = results.some(
        (r) => r.status === "rejected" && r.reason instanceof AdminAuthRequiredError,
      );
      if (authError) {
        setUnauthorized(true);
        return;
      }

      const [coverageResult, healthResult, qualityResult, duplicatesResult, reportsResult] =
        results;

      const coverage = coverageResult.status === "fulfilled" ? coverageResult.value : null;
      const health = healthResult.status === "fulfilled" ? healthResult.value : null;
      const quality = qualityResult.status === "fulfilled" ? qualityResult.value : null;
      const duplicates = duplicatesResult.status === "fulfilled" ? duplicatesResult.value : null;
      const reports = reportsResult.status === "fulfilled" ? reportsResult.value : null;

      const latestReport = reports?.reports?.[0] ?? null;

      setSummary({
        metadataCompletionPct: coverage?.summary.metadata_completion_pct ?? null,
        mappingCoveragePct: coverage?.summary.mapping_coverage_pct ?? null,
        recentPriceCoveragePct: coverage?.summary.recent_price_coverage_pct ?? null,
        duplicateRiskCount: duplicates?.summary.total_pairs ?? null,
        mappingQualityCriticalCount: quality?.summary.critical_count ?? null,
        priceSourceHealthWarningCount: health
          ? health.summary.blocked_source_count + health.summary.error_source_count
          : null,
        latestValidationStatus: latestReport ? (latestReport.valid ? "valid" : "invalid") : "none",
      });

      const allFailed = results.every((r) => r.status === "rejected");
      setStatus(allFailed ? "error" : "ready");
    });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Catalog Operations</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          One landing page for canonical catalog import/export, matching, duplicate review,
          mapping quality, coverage, and price source health.
        </p>

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            {status === "loading" && (
              <div className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                Loading catalog operations summary…
              </div>
            )}
            {status === "error" && (
              <div className="mb-6 rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
                Failed to load the catalog operations summary. Is the backend running?
              </div>
            )}
            {status === "ready" && summary && (
              <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7">
                <StatTile
                  label="Metadata completion"
                  value={formatPercent(summary.metadataCompletionPct)}
                />
                <StatTile
                  label="Mapping coverage"
                  value={formatPercent(summary.mappingCoveragePct)}
                />
                <StatTile
                  label="Recent price coverage"
                  value={formatPercent(summary.recentPriceCoveragePct)}
                />
                <StatTile label="Duplicate risks" value={formatCount(summary.duplicateRiskCount)} />
                <StatTile
                  label="Mapping quality critical"
                  value={formatCount(summary.mappingQualityCriticalCount)}
                />
                <StatTile
                  label="Price source health warnings"
                  value={formatCount(summary.priceSourceHealthWarningCount)}
                />
                <StatTile
                  label="Latest validation report"
                  value={formatValidationStatus(summary.latestValidationStatus)}
                />
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {OPS_CARDS.map((card) => (
                <Link
                  key={card.href}
                  href={card.href}
                  className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 hover:border-neutral-700 hover:bg-neutral-900/80"
                >
                  <div className="text-sm font-medium text-neutral-100">{card.title}</div>
                  <div className="mt-1 text-xs text-neutral-500">{card.description}</div>
                </Link>
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
