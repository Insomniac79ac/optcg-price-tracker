"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { VersionFooter } from "@/components/VersionFooter";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type SystemCheckResponse,
  fetchSystemCheck,
} from "@/lib/api";
import { formatPercent } from "@/lib/format";

type PageStatus =
  | "loading"
  | "ready"
  | "unauthorized"
  | "not_found"
  | "timeout"
  | "network_error"
  | "proxy_error"
  | "error";

interface ProxyErrorDetails {
  message: string;
  backendStatus?: number;
  bodyPreview?: string;
}

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
};

const CHECK_STATUS_STYLES: Record<string, string> = {
  pass: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  fail: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
};

export default function SystemCheckPage() {
  const [report, setReport] = useState<SystemCheckResponse | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);

  function load() {
    setStatus("loading");
    fetchSystemCheck()
      .then((data) => {
        setReport(data);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setStatus("unauthorized");
        else if (err instanceof AdminNotFoundError) setStatus("not_found");
        else if (err instanceof AdminTimeoutError) setStatus("timeout");
        else if (err instanceof AdminNetworkError) setStatus("network_error");
        else if (err instanceof AdminProxyError) {
          setProxyError({
            message: err.message,
            backendStatus: err.backendStatus,
            bodyPreview: err.bodyPreview,
          });
          setStatus("proxy_error");
        } else setStatus("error");
      });
  }

  useEffect(() => {
    // The initial mount owns this external system-check request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader
          title="System check"
          description="A read-only consistency sweep with exact-print operational lineage separated from legacy compatibility populations."
          actions={
            <>
              <ActionButton onClick={load}>Re-run</ActionButton>
            </>
          }
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/logs" className="text-sky-400 hover:underline">
            App logs
          </Link>
          <Link href="/admin/release-status" className="text-sky-400 hover:underline">
            Release status
          </Link>
          <Link href="/admin/catalog-coverage" className="text-sky-400 hover:underline">
            Catalog coverage
          </Link>
          <Link href="/admin/price-source-health" className="text-sky-400 hover:underline">
            Price source health
          </Link>
          <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:underline">
            Source mapping quality
          </Link>
          <Link href="/admin/card-duplicates" className="text-sky-400 hover:underline">
            Card duplicates
          </Link>
          <Link href="/admin/catalog-ops" className="text-sky-400 hover:underline">
            Catalog operations
          </Link>
        </div>

        {status === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {status === "loading" && <LoadingState>Running system check…</LoadingState>}

        {status === "not_found" && (
          <ErrorState>
            The system-check endpoint was not found (404). Is the backend up to date?
          </ErrorState>
        )}

        {status === "timeout" && (
          <ErrorState>
            Timed out waiting for the system check (15s). Is the backend running and reachable?
          </ErrorState>
        )}

        {status === "network_error" && (
          <ErrorState>
            Could not reach the API proxy. Check that the web and api containers are both
            running.
          </ErrorState>
        )}

        {status === "proxy_error" && proxyError && (
          <ErrorState>
            <p className="font-medium">{proxyError.message}</p>
            {proxyError.backendStatus !== undefined && (
              <p className="mt-1">backend_status: {proxyError.backendStatus}</p>
            )}
            {proxyError.bodyPreview && (
              <pre className="mt-3 max-h-48 overflow-auto rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-left text-xs whitespace-pre-wrap text-signal-red">
                {proxyError.bodyPreview}
              </pre>
            )}
          </ErrorState>
        )}

        {status === "error" && <ErrorState>Failed to run the system check. Is the backend running?</ErrorState>}

        {status === "ready" && report && (
          <>
            <StatGrid>
              <StatCard
                label="Overall status"
                value={<Badge label={report.status} className={`uppercase ${STATUS_STYLES[report.status] ?? ""}`} />}
              />
              <StatCard label="Checks total" value={report.summary.checks_total} />
              <StatCard label="Passed" value={report.summary.checks_passed} tone="good" />
              <StatCard
                label="Warnings"
                value={report.summary.warnings}
                tone={report.summary.warnings > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Critical"
                value={report.summary.critical}
                tone={report.summary.critical > 0 ? "bad" : "neutral"}
              />
            </StatGrid>

            <div className="mt-6">
              <CatalogOperationsSection catalogOperations={report.catalog_operations} />
            </div>

            <div className="mb-2 mt-6 text-xs text-text-muted">
              Check severity is reported by the backend. Informational compatibility populations do not imply an exact-pricing failure.
            </div>
            <DataTableShell isEmpty={report.checks.length === 0} emptyLabel="No checks reported.">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {report.checks.map((check) => (
                    <tr key={check.name}>
                      <td className="mono text-text-secondary">{check.name}</td>
                      <td>
                        <Badge
                          label={check.status}
                          className={
                            CHECK_STATUS_STYLES[check.status] ??
                            "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30"
                          }
                        />
                      </td>
                      <td>
                        <SeverityBadge severity={check.severity} />
                      </td>
                      <td className="text-text-secondary">{check.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>
          </>
        )}
        <VersionFooter />
      </main>
    </div>
  );
}

const OPS_STATUS_TONE: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  healthy: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  valid: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  degraded: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  invalid: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  none: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
};

const DEFAULT_OPS_STATUS_TONE = "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30";

function OpsStatusValue({ status }: { status: string }) {
  return <Badge label={status} className={`uppercase ${OPS_STATUS_TONE[status] ?? DEFAULT_OPS_STATUS_TONE}`} />;
}

function CatalogOperationsSection({
  catalogOperations,
}: {
  catalogOperations: SystemCheckResponse["catalog_operations"];
}) {
  const ops = catalogOperations;
  const modern = ops.modern_exact_print;
  const compatibility = ops.legacy_compatibility;
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-text-secondary">Catalog operations</h2>
        <Link href="/admin/catalog-ops" className="text-xs text-sky-400 hover:underline">
          Catalog operations dashboard →
        </Link>
      </div>
      <h3 className="mb-2 mt-4 text-sm font-medium text-text-primary">Modern exact-print operations</h3>
      <p className="mb-3 text-xs text-text-muted">Authoritative physical-print mapping, observation, and parent lineage.</p>
      <StatGrid>
        <StatCard label="Exact mappings" value={modern.mapping_identity.exact} />
        <StatCard label="Broken mapping lineage" value={modern.mapping_identity.broken_operational} tone={modern.mapping_identity.broken_operational > 0 ? "bad" : "good"} />
        <StatCard label="Active exact mappings" value={modern.mapping_operations.active_exact_mappings} />
        <StatCard label="Active exact mappings to non-priceable prints" value={modern.mapping_operations.active_exact_to_non_priceable_print} tone={modern.mapping_operations.active_exact_to_non_priceable_print > 0 ? "bad" : "good"} />
        <StatCard label="Operationally eligible exact mappings" value={modern.mapping_operations.operationally_eligible_exact_mappings} />
        <StatCard label="Exact mappings missing operational eligibility" value={modern.mapping_operations.exact_mappings_missing_expected_operational_eligibility} tone={modern.mapping_operations.exact_mappings_missing_expected_operational_eligibility > 0 ? "bad" : "good"} />
        <StatCard label="Exact observations" value={modern.observations.exact} />
        <StatCard label="Inconsistent observation lineage" value={modern.observations.broken_inconsistent} tone={modern.observations.broken_inconsistent > 0 ? "bad" : "good"} />
        <StatCard label="Physical prints" value={modern.parents.card_prints} />
        <StatCard label="Broken canonical Card parent lineage" value={modern.parents.card_prints_broken_canonical_card} tone={modern.parents.card_prints_broken_canonical_card > 0 ? "bad" : "good"} />
        <StatCard label="Active verified prints missing release product" value={modern.parents.active_verified_prints_missing_release_product} tone={modern.parents.active_verified_prints_missing_release_product > 0 ? "bad" : "good"} />
        <StatCard label="Broken release-product parent lineage" value={modern.parents.card_prints_broken_release_product} tone={modern.parents.card_prints_broken_release_product > 0 ? "bad" : "good"} />
        <StatCard label="Snapshots with broken CardPrint lineage" value={modern.parents.market_index_snapshots_broken_card_print} tone={modern.parents.market_index_snapshots_broken_card_print > 0 ? "bad" : "good"} />
        <StatCard label="Price source health" value={<OpsStatusValue status={ops.price_source_health_status} />} />
      </StatGrid>

      <div className="mt-5 rounded-panel border border-border-default bg-bg-surface p-4">
        <h3 className="text-sm font-medium text-text-primary">Legacy compatibility / informational</h3>
        <p className="mb-3 mt-1 text-xs text-text-muted">Grandfathered Card mappings and Card-keyed collection or wishlist references. These counts are not modern exact-pricing failures.</p>
        <StatGrid>
          <StatCard label="Grandfathered mappings" value={compatibility.grandfathered_mappings} />
          <StatCard label="Legacy lineage-less observations" value={modern.observations.legacy_lineage_less} />
          <StatCard label="Compatibility Card references" value={compatibility.mapping_card_references} />
          <StatCard label="Broken compatibility pointers" value={compatibility.broken_mapping_card_pointers} tone={compatibility.broken_mapping_card_pointers > 0 ? "bad" : "neutral"} />
          <StatCard label="Collection Card references" value={compatibility.collection_items} />
          <StatCard label="Broken collection references" value={compatibility.broken_collection_item_card_pointers} tone={compatibility.broken_collection_item_card_pointers > 0 ? "bad" : "neutral"} />
          <StatCard label="Wishlist Card references" value={compatibility.wishlist_items} />
          <StatCard label="Broken wishlist references" value={compatibility.broken_wishlist_item_card_pointers} tone={compatibility.broken_wishlist_item_card_pointers > 0 ? "bad" : "neutral"} />
          <StatCard label="Legacy metadata completion" value={formatPercent(ops.metadata_completion_pct)} />
          <StatCard label="Legacy Card mapping coverage" value={formatPercent(ops.mapping_coverage_pct)} />
          <StatCard label="Legacy Card recent-price coverage" value={formatPercent(ops.recent_price_coverage_pct)} />
        </StatGrid>
      </div>

      <h3 className="mb-2 mt-5 text-sm font-medium text-text-primary">Catalogue administration</h3>
      <StatGrid>
        <StatCard label="Card audit" value={<OpsStatusValue status={ops.card_audit_status} />} />
        <StatCard
          label="Duplicate risk"
          value={ops.duplicate_risk_count}
          tone={ops.duplicate_risk_count > 0 ? "bad" : "good"}
        />
        <StatCard
          label="Mapping quality critical"
          value={ops.mapping_quality_critical_count}
          tone={ops.mapping_quality_critical_count > 0 ? "bad" : "good"}
        />
      </StatGrid>
      <div className="panel mt-3 px-4 py-3">
        <div className="flex items-baseline justify-between">
          <div className="text-xs uppercase tracking-wide text-text-muted">
            Latest import validation report
          </div>
          <OpsStatusValue status={ops.latest_import_validation_status} />
        </div>
        {ops.warnings.length > 0 ? (
          <ul className="mt-2 list-inside list-disc text-xs text-signal-warning">
            {ops.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-text-muted">No catalog-operations warnings.</p>
        )}
      </div>
    </div>
  );
}
