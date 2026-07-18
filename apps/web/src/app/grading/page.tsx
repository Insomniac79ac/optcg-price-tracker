"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { FormField } from "@/components/FormField";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  GRADING_COMPANY_OPTIONS,
  GRADING_SUBMISSION_STATUSES,
  type CollectionItem,
  type GradingSubmission,
  type GradingSubmissionInput,
  type GradingSummary,
  createGradingSubmission,
  deleteGradingSubmission,
  fetchCollectionItems,
  fetchGradingSubmissions,
  fetchGradingSummary,
  updateGradingSubmission,
} from "@/lib/api";
import { cardDisplayName, formatDate, formatJpy } from "@/lib/format";

const ALL_OPTION = { value: "", label: "All" };
const LIMIT_OPTIONS = [25, 50, 100, 200] as const;
const STATUS_FILTER_OPTIONS = [
  ALL_OPTION,
  ...GRADING_SUBMISSION_STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") })),
];

function orNotSet(value: string | number | null): string {
  return value === null || value === "" ? "not set" : String(value);
}

interface FormState {
  collection_item_id: string;
  grading_company: string;
  submission_name: string;
  submission_status: string;
  declared_value_jpy: string;
  grading_fee_jpy: string;
  shipping_fee_jpy: string;
  insurance_fee_jpy: string;
  other_fee_jpy: string;
  submitted_at: string;
  expected_return_date: string;
  received_at: string;
  tracking_number: string;
  final_grade: string;
  cert_number: string;
  graded_value_jpy: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  collection_item_id: "",
  grading_company: "PSA",
  submission_name: "",
  submission_status: "planned",
  declared_value_jpy: "",
  grading_fee_jpy: "",
  shipping_fee_jpy: "",
  insurance_fee_jpy: "",
  other_fee_jpy: "",
  submitted_at: "",
  expected_return_date: "",
  received_at: "",
  tracking_number: "",
  final_grade: "",
  cert_number: "",
  graded_value_jpy: "",
  notes: "",
};

function submissionToForm(s: GradingSubmission): FormState {
  return {
    collection_item_id: String(s.collection_item_id),
    grading_company: s.grading_company,
    submission_name: s.submission_name ?? "",
    submission_status: s.submission_status,
    declared_value_jpy: s.declared_value_jpy === null ? "" : String(s.declared_value_jpy),
    grading_fee_jpy: s.grading_fee_jpy === null ? "" : String(s.grading_fee_jpy),
    shipping_fee_jpy: s.shipping_fee_jpy === null ? "" : String(s.shipping_fee_jpy),
    insurance_fee_jpy: s.insurance_fee_jpy === null ? "" : String(s.insurance_fee_jpy),
    other_fee_jpy: s.other_fee_jpy === null ? "" : String(s.other_fee_jpy),
    submitted_at: s.submitted_at ?? "",
    expected_return_date: s.expected_return_date ?? "",
    received_at: s.received_at ?? "",
    tracking_number: s.tracking_number ?? "",
    final_grade: s.final_grade ?? "",
    cert_number: s.cert_number ?? "",
    graded_value_jpy: s.graded_value_jpy === null ? "" : String(s.graded_value_jpy),
    notes: s.notes ?? "",
  };
}

export default function GradingPage() {
  return (
    <Suspense fallback={null}>
      <GradingPageInner />
    </Suspense>
  );
}

function GradingPageInner() {
  const searchParams = useSearchParams();
  const preselectedItemId = searchParams.get("item_id");

  const [submissions, setSubmissions] = useState<GradingSubmission[]>([]);
  const [total, setTotal] = useState(0);
  const [listStatus, setListStatus] = useState<"loading" | "error" | "ready">("loading");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [summary, setSummary] = useState<GradingSummary | null>(null);

  const [collectionItems, setCollectionItems] = useState<CollectionItem[]>([]);

  const [statusFilter, setStatusFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [cardCodeInput, setCardCodeInput] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");

  const [form, setForm] = useState<FormState>(() =>
    preselectedItemId
      ? { ...EMPTY_FORM, collection_item_id: preselectedItemId }
      : EMPTY_FORM,
  );
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => setCardCodeFilter(cardCodeInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [cardCodeInput]);

  function refreshSummary() {
    fetchGradingSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
  }

  function refreshCollectionItems() {
    fetchCollectionItems({ limit: 500 })
      .then((data) => setCollectionItems(data.items))
      .catch(() => setCollectionItems([]));
  }

  function refreshList() {
    fetchGradingSubmissions({
      status: statusFilter || undefined,
      grading_company: companyFilter || undefined,
      card_code: cardCodeFilter || undefined,
      limit,
      offset,
    })
      .then((data) => {
        setSubmissions(data.items);
        setTotal(data.total);
        setListStatus("ready");
      })
      .catch(() => setListStatus("error"));
  }

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filter's result set is otherwise almost certainly out of range for
  // the new one.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, companyFilter, cardCodeFilter, limit]);

  useEffect(() => {
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, companyFilter, cardCodeFilter, limit, offset]);

  useEffect(() => {
    refreshSummary();
    refreshCollectionItems();
  }, []);

  const companyOptions = useMemo(() => {
    const values = Array.from(new Set(submissions.map((s) => s.grading_company))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [submissions]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function startEdit(s: GradingSubmission) {
    setEditingId(s.id);
    setForm(submissionToForm(s));
    setFormError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  }

  function parseOptionalInt(value: string, label: string): number | null | undefined {
    if (value === "") return null;
    const parsed = Number(value);
    if (Number.isNaN(parsed) || parsed < 0) {
      setFormError(`${label} must be 0 or greater.`);
      return undefined;
    }
    return parsed;
  }

  function validateForm(): GradingSubmissionInput | null {
    const collectionItemId = Number(form.collection_item_id);
    if (!form.collection_item_id || Number.isNaN(collectionItemId)) {
      setFormError("Select a collection item.");
      return null;
    }
    if (!form.grading_company.trim()) {
      setFormError("Grading company is required.");
      return null;
    }

    const declaredValue = parseOptionalInt(form.declared_value_jpy, "Declared value");
    if (declaredValue === undefined) return null;
    const gradingFee = parseOptionalInt(form.grading_fee_jpy, "Grading fee");
    if (gradingFee === undefined) return null;
    const shippingFee = parseOptionalInt(form.shipping_fee_jpy, "Shipping fee");
    if (shippingFee === undefined) return null;
    const insuranceFee = parseOptionalInt(form.insurance_fee_jpy, "Insurance fee");
    if (insuranceFee === undefined) return null;
    const otherFee = parseOptionalInt(form.other_fee_jpy, "Other fee");
    if (otherFee === undefined) return null;
    const gradedValue = parseOptionalInt(form.graded_value_jpy, "Graded value");
    if (gradedValue === undefined) return null;

    return {
      collection_item_id: collectionItemId,
      grading_company: form.grading_company.trim(),
      submission_name: form.submission_name || null,
      submission_status: form.submission_status,
      declared_value_jpy: declaredValue,
      grading_fee_jpy: gradingFee,
      shipping_fee_jpy: shippingFee,
      insurance_fee_jpy: insuranceFee,
      other_fee_jpy: otherFee,
      submitted_at: form.submitted_at || null,
      expected_return_date: form.expected_return_date || null,
      received_at: form.received_at || null,
      tracking_number: form.tracking_number || null,
      final_grade: form.final_grade || null,
      cert_number: form.cert_number || null,
      graded_value_jpy: gradedValue,
      notes: form.notes || null,
    };
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const body = validateForm();
    if (!body) return;

    setSaving(true);
    try {
      if (editingId !== null) {
        await updateGradingSubmission(editingId, body);
      } else {
        await createGradingSubmission(body);
      }
      setForm(EMPTY_FORM);
      setEditingId(null);
      refreshList();
      refreshSummary();
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : editingId !== null
            ? "Failed to update grading submission."
            : "Failed to create grading submission.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(submission: GradingSubmission) {
    const confirmed = window.confirm(
      `Delete the ${submission.grading_company} submission for ${submission.card_code}? This cannot be undone.`,
    );
    if (!confirmed) return;

    setActionError(null);
    setPendingDeleteId(submission.id);
    try {
      await deleteGradingSubmission(submission.id);
      if (editingId === submission.id) cancelEdit();
      refreshList();
      refreshSummary();
    } catch {
      setActionError("Failed to delete grading submission.");
    } finally {
      setPendingDeleteId(null);
    }
  }

  async function handleMarkStatus(submission: GradingSubmission, status: string) {
    setActionError(null);
    try {
      const extra: Partial<GradingSubmissionInput> = {};
      const today = new Date().toISOString().slice(0, 10);
      if (status === "submitted" && !submission.submitted_at) extra.submitted_at = today;
      if (status === "received" && !submission.received_at) extra.received_at = today;
      await updateGradingSubmission(submission.id, { submission_status: status, ...extra });
      refreshList();
      refreshSummary();
    } catch {
      setActionError(`Failed to mark submission as ${status}.`);
    }
  }

  const isEditing = editingId !== null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Grading</h1>
          {listStatus === "ready" && (
            <span className="text-sm text-neutral-500">
              {total} submission{total === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard label="Total submissions" value={summary.total_submissions} />
            <StatCard label="Planned" value={summary.by_status.planned ?? 0} />
            <StatCard
              label="Submitted/Grading"
              value={(summary.by_status.submitted ?? 0) + (summary.by_status.grading ?? 0)}
            />
            <StatCard label="Received" value={summary.by_status.received ?? 0} />
            <StatCard label="Items waiting return" value={summary.items_waiting_return} />
            <StatCard
              label="Total declared value"
              value={formatJpy(summary.total_declared_value_jpy)}
            />
            <StatCard
              label="Total grading cost"
              value={formatJpy(summary.total_grading_cost_jpy)}
            />
            <StatCard
              label="Total graded value"
              value={formatJpy(summary.total_graded_value_jpy)}
            />
            <StatCard
              label="Unrealized gain after grading"
              value={formatJpy(summary.total_unrealized_gain_after_grading_jpy)}
            />
            <StatCard
              label="Average grade"
              value={summary.average_grade === null ? "not set" : summary.average_grade}
            />
          </div>
        )}

        <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-200">
            {isEditing ? "Edit grading submission" : "Add grading submission"}
          </h2>

          {formError && (
            <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
              {formError}
            </div>
          )}

          <form onSubmit={submitForm} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <FormField label="Collection item">
                <select
                  value={form.collection_item_id}
                  onChange={(e) => updateField("collection_item_id", e.target.value)}
                  disabled={isEditing}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 disabled:opacity-50"
                >
                  <option value="">Select an item…</option>
                  {collectionItems.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.card_code} — {cardDisplayName(item)} ({item.condition_label ?? "raw"})
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Grading company">
                <input
                  type="text"
                  list="grading-company-options"
                  value={form.grading_company}
                  onChange={(e) => updateField("grading_company", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
                <datalist id="grading-company-options">
                  {GRADING_COMPANY_OPTIONS.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </FormField>

              <FormField label="Submission name">
                <input
                  type="text"
                  value={form.submission_name}
                  onChange={(e) => updateField("submission_name", e.target.value)}
                  placeholder="July PSA batch"
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                />
              </FormField>

              <FormField label="Status">
                <select
                  value={form.submission_status}
                  onChange={(e) => updateField("submission_status", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                >
                  {GRADING_SUBMISSION_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </FormField>

              <FormField label="Declared value (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.declared_value_jpy}
                  onChange={(e) => updateField("declared_value_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Grading fee (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.grading_fee_jpy}
                  onChange={(e) => updateField("grading_fee_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Shipping fee (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.shipping_fee_jpy}
                  onChange={(e) => updateField("shipping_fee_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Insurance fee (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.insurance_fee_jpy}
                  onChange={(e) => updateField("insurance_fee_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Other fee (JPY)">
                <input
                  type="number"
                  min={0}
                  value={form.other_fee_jpy}
                  onChange={(e) => updateField("other_fee_jpy", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Submitted date">
                <input
                  type="date"
                  value={form.submitted_at}
                  onChange={(e) => updateField("submitted_at", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Expected return date">
                <input
                  type="date"
                  value={form.expected_return_date}
                  onChange={(e) => updateField("expected_return_date", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              <FormField label="Tracking number">
                <input
                  type="text"
                  value={form.tracking_number}
                  onChange={(e) => updateField("tracking_number", e.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                />
              </FormField>

              {isEditing && (
                <>
                  <FormField label="Received date">
                    <input
                      type="date"
                      value={form.received_at}
                      onChange={(e) => updateField("received_at", e.target.value)}
                      className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                    />
                  </FormField>

                  <FormField label="Final grade">
                    <input
                      type="text"
                      value={form.final_grade}
                      onChange={(e) => updateField("final_grade", e.target.value)}
                      placeholder="PSA 10"
                      className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
                    />
                  </FormField>

                  <FormField label="Cert number">
                    <input
                      type="text"
                      value={form.cert_number}
                      onChange={(e) => updateField("cert_number", e.target.value)}
                      className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                    />
                  </FormField>

                  <FormField label="Graded value (JPY)">
                    <input
                      type="number"
                      min={0}
                      value={form.graded_value_jpy}
                      onChange={(e) => updateField("graded_value_jpy", e.target.value)}
                      className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                    />
                  </FormField>
                </>
              )}

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
                {saving ? "Saving…" : isEditing ? "Update submission" : "Create submission"}
              </button>
              {isEditing && (
                <button
                  type="button"
                  onClick={cancelEdit}
                  disabled={saving}
                  className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                >
                  Cancel
                </button>
              )}
            </div>
          </form>
        </section>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={STATUS_FILTER_OPTIONS}
          />
          <FilterSelect
            label="Company"
            value={companyFilter}
            onChange={setCompanyFilter}
            options={companyOptions}
          />
          <input
            type="text"
            value={cardCodeInput}
            onChange={(e) => setCardCodeInput(e.target.value)}
            placeholder="Filter by card code…"
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
          />
        </div>

        {actionError && (
          <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {actionError}
          </div>
        )}

        {listStatus === "loading" && <LoadingState>Loading grading submissions…</LoadingState>}

        {listStatus === "error" && (
          <ErrorState>Failed to load grading submissions from the API.</ErrorState>
        )}

        {listStatus === "ready" && submissions.length === 0 && (
          <EmptyState>No grading submissions yet</EmptyState>
        )}

        {listStatus === "ready" && submissions.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Qty</th>
                  <th className="px-2 py-1.5 font-medium">Company</th>
                  <th className="px-2 py-1.5 font-medium">Submission</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Declared value</th>
                  <th className="px-2 py-1.5 font-medium">Total cost</th>
                  <th className="px-2 py-1.5 font-medium">Submitted</th>
                  <th className="px-2 py-1.5 font-medium">Expected return</th>
                  <th className="px-2 py-1.5 font-medium">Received</th>
                  <th className="px-2 py-1.5 font-medium">Grade</th>
                  <th className="px-2 py-1.5 font-medium">Cert #</th>
                  <th className="px-2 py-1.5 font-medium">Graded value</th>
                  <th className="px-2 py-1.5 font-medium">Notes</th>
                  <th className="px-2 py-1.5 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-2 py-1.5 font-mono text-neutral-400">{s.card_code}</td>
                    <td className="px-2 py-1.5 font-medium text-neutral-100">
                      {cardDisplayName(s)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">{s.quantity}</td>
                    <td className="px-2 py-1.5 text-neutral-200">{s.grading_company}</td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {orNotSet(s.submission_name)}
                    </td>
                    <td className="px-2 py-1.5">
                      <GradingStatusBadge status={s.submission_status} />
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatJpy(s.declared_value_jpy)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatJpy(s.total_cost_jpy)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">{formatDate(s.submitted_at)}</td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {formatDate(s.expected_return_date)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">{formatDate(s.received_at)}</td>
                    <td className="px-2 py-1.5 text-neutral-200">{orNotSet(s.final_grade)}</td>
                    <td className="px-2 py-1.5 text-neutral-400">{orNotSet(s.cert_number)}</td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatJpy(s.graded_value_jpy)}
                    </td>
                    <td className="max-w-[10rem] px-2 py-1.5 text-neutral-500">
                      {orNotSet(s.notes)}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => startEdit(s)}
                          className="text-xs font-medium text-sky-400 hover:text-sky-300"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(s)}
                          disabled={pendingDeleteId === s.id}
                          className="text-xs font-medium text-rose-400 hover:text-rose-300 disabled:opacity-50"
                        >
                          Delete
                        </button>
                        {(
                          [
                            "submitted",
                            "grading",
                            "shipped_back",
                            "received",
                            "cancelled",
                          ] as const
                        )
                          .filter((status) => status !== s.submission_status)
                          .map((status) => (
                            <button
                              key={status}
                              onClick={() => handleMarkStatus(s, status)}
                              className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
                            >
                              Mark {status.replace(/_/g, " ")}
                            </button>
                          ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {listStatus === "ready" && (
          <div className="mt-3">
            <PaginationControls
              offset={offset}
              limit={limit}
              total={total}
              onOffsetChange={setOffset}
              limitOptions={LIMIT_OPTIONS}
              onLimitChange={setLimit}
            />
          </div>
        )}

        <div className="mt-6 flex flex-wrap gap-3 text-xs">
          <Link
            href="/collection"
            className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection
          </Link>
        </div>
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 truncate text-2xl font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-neutral-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
