"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { PageHeader } from "@/components/ui/PageHeader";
import { PinnedViewsSection } from "@/components/ui/PinnedViewsSection";
import { QuickActionBar } from "@/components/ui/QuickActionBar";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
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
        <PageHeader
          title="Catalog Operations"
          description="One landing page for canonical catalog import/export, matching, duplicate review, mapping quality, coverage, and price source health."
          actions={<AdminLogoutButton />}
        />

        {unauthorized && <AdminAuthGate onTokenSaved={() => window.location.reload()} />}

        {!unauthorized && (
          <>
            <QuickActionBar
              actions={[
                { label: "Source Mapping Quality", href: "/admin/source-mapping-quality" },
                { label: "Catalog Coverage", href: "/admin/catalog-coverage" },
                { label: "Price Source Health", href: "/admin/price-source-health" },
              ]}
            />

            {status === "loading" && (
              <div className="mb-6 rounded-panel border border-border-default bg-bg-surface p-8 text-center text-sm text-text-muted">
                Loading catalog operations summary…
              </div>
            )}
            {status === "error" && (
              <div className="mb-6 rounded-panel border border-signal-red/40 bg-signal-red/10 p-8 text-center text-sm text-signal-red">
                Failed to load the catalog operations summary. Is the backend running?
              </div>
            )}
            {status === "ready" && summary && (
              <div className="mb-6">
                <StatGrid>
                  <StatCard
                    label="Metadata completion"
                    value={formatPercent(summary.metadataCompletionPct)}
                  />
                  <StatCard
                    label="Mapping coverage"
                    value={formatPercent(summary.mappingCoveragePct)}
                  />
                  <StatCard
                    label="Recent price coverage"
                    value={formatPercent(summary.recentPriceCoveragePct)}
                  />
                  <StatCard label="Duplicate risks" value={formatCount(summary.duplicateRiskCount)} />
                  <StatCard
                    label="Mapping quality critical"
                    value={formatCount(summary.mappingQualityCriticalCount)}
                  />
                  <StatCard
                    label="Price source health warnings"
                    value={formatCount(summary.priceSourceHealthWarningCount)}
                  />
                  <StatCard
                    label="Latest validation report"
                    value={formatValidationStatus(summary.latestValidationStatus)}
                  />
                </StatGrid>
              </div>
            )}

            <PinnedViewsSection title="Pinned Admin Views" />

            <div
              data-testid="catalog-ops-links"
              className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
            >
              {OPS_CARDS.map((card) => (
                <Link key={card.href} href={card.href} className="vault-card block p-4">
                  <div className="text-sm font-medium text-text-primary">{card.title}</div>
                  <div className="mt-1 text-xs text-text-muted">{card.description}</div>
                </Link>
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
