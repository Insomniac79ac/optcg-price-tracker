import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProposalApprovalError,
  type ApproveExactProposalResponse,
  type ProposalReviewGroupDetail,
} from "@/lib/proposalReview";

const { approveExactProposal, refresh } = vi.hoisted(() => ({
  approveExactProposal: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/proposalReview", async () => {
  const actual = await vi.importActual<typeof import("@/lib/proposalReview")>("@/lib/proposalReview");
  return { ...actual, approveExactProposal };
});

import { ExactProposalApprovalPanel } from "./ExactProposalApprovalPanel";
import { makeAlternative, makeReviewDetail } from "../proposalReview.fixtures";

function approvalResponse(overrides: Partial<ApproveExactProposalResponse> = {}): ApproveExactProposalResponse {
  return {
    proposal_group_id: 1127,
    review_status: "approved",
    selected_alternative_id: 9001,
    resulting_source_card_mapping_id: 836,
    card_print_id: 501,
    source: "yuyutei",
    source_candidate_id: 9911,
    reviewed_at: "2026-09-22T10:01:02Z",
    reviewed_by: "reviewer@example.com",
    review_notes: null,
    decision_basis_updated_at: "2026-09-21T02:00:00Z",
    mapping_created: true,
    mapping_reused: false,
    candidate_status: "family_matched",
    idempotent_replay: false,
    collection_triggered: false,
    price_observation_written: false,
    eligible_for_future_scheduled_collection: true,
    ...overrides,
  };
}

function renderPanel(proposal = makeReviewDetail()) {
  const onReload = vi.fn();
  const view = render(<ExactProposalApprovalPanel proposal={proposal} onReload={onReload} />);
  return { ...view, onReload };
}

function selectAndOpen() {
  fireEvent.click(screen.getByRole("radio", { name: /Roronoa Zoro · CardPrint #501/ }));
  fireEvent.click(screen.getByRole("button", { name: "Review approval confirmation" }));
  return screen.getByRole("dialog", { name: "Confirm exact proposal approval" });
}

function completeConfirmation(dialog = selectAndOpen()) {
  fireEvent.click(within(dialog).getByRole("checkbox", { name: "I reviewed the source evidence and the exact physical printing." }));
  fireEvent.click(within(dialog).getByRole("checkbox", { name: "I understand this authorizes future scheduled collection but does not collect or create a price now." }));
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Typed confirmation" }), { target: { value: "APPROVE PROPOSAL 1127" } });
  return dialog;
}

async function submitWithError(error: ProposalApprovalError) {
  approveExactProposal.mockRejectedValueOnce(error);
  renderPanel();
  const dialog = completeConfirmation();
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

describe("ExactProposalApprovalPanel eligibility", () => {
  beforeEach(() => {
    approveExactProposal.mockReset();
    refresh.mockReset();
  });

  it("shows a pending current exact proposal but requires explicit printing selection", () => {
    renderPanel();
    expect(screen.getByRole("heading", { name: "Approve exact proposal" })).toBeInTheDocument();
    expect(screen.getByText("Eligible for exact-approval review")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /CardPrint #501/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Review approval confirmation" })).toBeDisabled();
    expect(screen.getByLabelText(/Review note/)).toHaveAttribute("maxlength", "2000");
    fireEvent.click(screen.getByRole("radio", { name: /CardPrint #501/ }));
    expect(screen.getByRole("button", { name: "Review approval confirmation" })).toBeEnabled();
  });

  it("shows an approved proposal as a terminal read-only decision", () => {
    renderPanel(makeReviewDetail({
      review_status: "approved",
      reviewed_at: "2026-09-22T10:01:02Z",
      reviewed_by: "reviewer@example.com",
      review_notes: "Checked physical print",
      selected_alternative_id: 9001,
      decision_basis_updated_at: "2026-09-21T02:00:00Z",
      resulting_source_card_mapping_id: 836,
      resulting_mapping: { id: 836 },
      alternatives: [makeAlternative({ review_disposition: "approved", reviewed_at: "2026-09-22T10:01:02Z" })],
    }));
    expect(screen.getByRole("heading", { name: "Approved" })).toBeInTheDocument();
    expect(screen.getByText("Mapping #836")).toBeInTheDocument();
    expect(screen.getByText("reviewer@example.com")).toBeInTheDocument();
    expect(screen.getByText("Checked physical print")).toBeInTheDocument();
    expect(screen.getByText(/Eligible for future scheduled collection/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it.each([
    ["rejected", makeReviewDetail({ review_status: "rejected" }), /terminal rejected decision/],
    ["ambiguous", makeReviewDetail({ resolution_status: "ambiguous" }), /multiple physical printings remain/],
    ["unresolved identity", makeReviewDetail({ resolution_status: "unresolved_identity", canonical_card: null, canonical_card_id: null }), /no canonical card identity/],
    ["release unresolved", makeReviewDetail({ resolution_status: "release_unresolved", release: null, release_product_id: null }), /no authoritative release product/],
    ["superseded", makeReviewDetail({ superseded_at: "2026-09-22T00:00:00Z" }), /has been superseded/],
    ["populated result", makeReviewDetail({ resulting_source_card_mapping_id: 836 }), /mapping is already linked/],
    ["zero alternatives", makeReviewDetail({ alternatives: [], alternative_count: 0 }), /no printing alternative/],
    ["multiple alternatives", makeReviewDetail({ alternatives: [makeAlternative(), makeAlternative({ alternative_id: 9002, card_print_id: 502, recommended: false })], alternative_count: 2 }), /multiple printing alternatives/],
    ["multiple recommended alternatives", makeReviewDetail({ recommended_alternative_count: 2 }), /not exactly one recommended printing/],
    ["alternative from another proposal", makeReviewDetail({ alternatives: [makeAlternative({ proposal_group_id: 999 })] }), /does not belong to this proposal/],
    ["missing evidence digest", makeReviewDetail({ evidence_digest: "" }), /evidence digest is missing/],
    ["missing resolver version", makeReviewDetail({ resolver_version: "" }), /resolver version is missing/],
    ["missing updated_at", makeReviewDetail({ updated_at: "" }), /proposal update time is missing/],
  ])("blocks %s without an approval action", (_label, proposal, message) => {
    renderPanel(proposal as ProposalReviewGroupDetail);
    expect(screen.getByText(message as RegExp)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approval confirmation/i })).not.toBeInTheDocument();
  });
});

describe("ExactProposalApprovalPanel confirmation and request", () => {
  beforeEach(() => {
    approveExactProposal.mockReset();
    refresh.mockReset();
  });

  it("opens without sending, requires both acknowledgements and the exact phrase, and cancels without sending", () => {
    renderPanel();
    const opener = screen.getByRole("button", { name: "Review approval confirmation" });
    fireEvent.click(screen.getByRole("radio", { name: /CardPrint #501/ }));
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Confirm exact proposal approval" });
    expect(dialog).toHaveFocus();
    expect(approveExactProposal).not.toHaveBeenCalled();
    const finalButton = within(dialog).getByRole("button", { name: "Approve exact proposal" });
    expect(finalButton).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /reviewed the source evidence/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /future scheduled collection/ }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Typed confirmation" }), { target: { value: "APPROVE PROPOSAL 1128" } });
    expect(finalButton).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(approveExactProposal).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /CardPrint #501/ })).toBeChecked();
    expect(screen.getByLabelText(/Review note/)).toHaveValue("");
  });

  it("sends exactly one constrained request, trimming a note and preserving updated_at exactly", async () => {
    approveExactProposal.mockResolvedValueOnce(approvalResponse());
    const { onReload } = renderPanel();
    fireEvent.change(screen.getByLabelText(/Review note/), { target: { value: "  inspected exact foil  " } });
    const dialog = completeConfirmation();
    const submit = within(dialog).getByRole("button", { name: "Approve exact proposal" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(approveExactProposal).toHaveBeenCalledTimes(1));
    const [id, body, options] = approveExactProposal.mock.calls[0];
    expect(id).toBe(1127);
    expect(body).toEqual({
      selected_alternative_id: 9001,
      expected_evidence_digest: "a".repeat(64),
      expected_resolver_version: "source-mapping-v4",
      expected_updated_at: "2026-09-21T02:00:00Z",
      review_note: "inspected exact foil",
    });
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(body).not.toHaveProperty("reviewed_by");
    expect(body).not.toHaveProperty("card_print_id");
    expect(body).not.toHaveProperty("actor_assertion");
    expect(body).not.toHaveProperty("ADMIN_TOKEN");
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(onReload).toHaveBeenCalledTimes(1);
    expect(onReload).toHaveBeenCalledWith({ silent: true });
  });

  it("omits an empty trimmed note", async () => {
    approveExactProposal.mockResolvedValueOnce(approvalResponse());
    renderPanel();
    fireEvent.change(screen.getByLabelText(/Review note/), { target: { value: "   " } });
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    await waitFor(() => expect(approveExactProposal).toHaveBeenCalled());
    expect(approveExactProposal.mock.calls[0][1]).not.toHaveProperty("review_note");
  });

  it("preserves the typed note after an ordinary backend refusal", async () => {
    approveExactProposal.mockRejectedValueOnce(new ProposalApprovalError({
      message: "This print is inactive.",
      status: 409,
      code: "print_inactive",
    }));
    renderPanel();
    fireEvent.change(screen.getByLabelText(/Review note/), { target: { value: "Keep this context" } });
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    await screen.findByText(/This print is inactive.*Nothing was approved/i);
    expect(screen.getByLabelText(/Review note/)).toHaveValue("Keep this context");
  });

  it("disables every modal control while one request is in flight", async () => {
    let resolve!: (response: ApproveExactProposalResponse) => void;
    approveExactProposal.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderPanel();
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    await waitFor(() => expect(within(dialog).getByText("Approving exact proposal…")).toBeInTheDocument());
    for (const control of within(dialog).getAllByRole("button").concat(within(dialog).getAllByRole("checkbox"), within(dialog).getAllByRole("textbox"))) {
      expect(control).toBeDisabled();
    }
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    resolve(approvalResponse());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("aborts the one in-flight browser request when the component unmounts", async () => {
    approveExactProposal.mockReturnValueOnce(new Promise(() => undefined));
    const { unmount } = renderPanel();
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    await waitFor(() => expect(approveExactProposal).toHaveBeenCalledTimes(1));
    const signal = approveExactProposal.mock.calls[0][2].signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("resets selection when the proposal concurrency data changes", () => {
    const { rerender } = renderPanel();
    fireEvent.click(screen.getByRole("radio", { name: /CardPrint #501/ }));
    expect(screen.getByRole("radio", { name: /CardPrint #501/ })).toBeChecked();
    rerender(<ExactProposalApprovalPanel proposal={makeReviewDetail({ updated_at: "2026-09-22T04:00:00Z" })} onReload={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /CardPrint #501/ })).not.toBeChecked();
  });
});

describe("ExactProposalApprovalPanel results and refusals", () => {
  beforeEach(() => {
    approveExactProposal.mockReset();
    refresh.mockReset();
  });

  it.each([
    ["created", { mapping_created: true, mapping_reused: false }, "Created"],
    ["reused", { mapping_created: false, mapping_reused: true }, "Reused"],
  ])("shows a verified %s result and collector safety", async (_label, overrides, mappingLabel) => {
    approveExactProposal.mockResolvedValueOnce(approvalResponse(overrides));
    renderPanel();
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    expect(await screen.findByRole("heading", { name: "Approved" })).toBeInTheDocument();
    expect(screen.getByText("reviewer@example.com")).toBeInTheDocument();
    expect(screen.getByText("family_matched")).toBeInTheDocument();
    expect(screen.getByText(mappingLabel)).toBeInTheDocument();
    expect(screen.getByText("Eligible for a future run")).toBeInTheDocument();
    expect(screen.getByText("No immediate collection was triggered. No price observation was written.")).toBeInTheDocument();
  });

  it("labels an idempotent replay as an existing decision", async () => {
    approveExactProposal.mockResolvedValueOnce(approvalResponse({ idempotent_replay: true, mapping_created: false, mapping_reused: true }));
    renderPanel();
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    expect(await screen.findByText("This exact approval was already recorded. No duplicate mapping or decision was created.")).toBeInTheDocument();
  });

  it.each([
    ["actor failure", 401, "admin_actor_assertion_invalid", /admin approval session could not be verified/, false],
    ["unauthorized", 403, "forbidden", /not authorized/, false],
    ["missing proposal", 404, "proposal_not_found", /no longer exists/, true],
    ["stale proposal", 409, "proposal_updated", /changed after the page was loaded/, true],
    ["rejected mapping", 409, "existing_mapping_was_rejected", /stored mapping was rejected.*Nothing was approved/i, false],
    ["conflicting print", 409, "existing_mapping_names_another_print", /stored mapping was rejected.*Nothing was approved/i, false],
    ["duplicate listings", 409, "multiple_mappings_for_listing", /stored mapping was rejected.*Nothing was approved/i, false],
    ["validation", 422, "validation_error", /did not pass validation.*Nothing was approved/i, false],
    ["server error", 500, "internal_error", /result is uncertain/, true],
    ["network timeout", 0, "request_timeout", /result is uncertain/, true],
  ])("handles %s without showing approval", async (_label, status, code, expected, reload) => {
    const payload = status === 422
      ? { detail: [{ msg: "Evidence digest must contain 64 characters." }] }
      : { detail: { code, message: "The stored mapping was rejected." } };
    await submitWithError(new ProposalApprovalError({
      message: status === 422 ? "Validation error" : "The stored mapping was rejected.",
      status,
      code,
      payload,
      uncertain: status === 0 || status >= 500,
    }));
    expect(screen.getByText(expected as RegExp)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Approved" })).not.toBeInTheDocument();
    expect(Boolean(screen.queryByRole("button", { name: "Reload proposal" }))).toBe(reload);
  });

  it("treats a mismatched success payload as uncertain and requires reload", async () => {
    approveExactProposal.mockResolvedValueOnce(approvalResponse({ card_print_id: 999 }));
    renderPanel();
    const dialog = completeConfirmation();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve exact proposal" }));
    expect(await screen.findByText(/approval result is uncertain/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload proposal" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Approved" })).not.toBeInTheDocument();
  });

  it("closes on Escape before submission and restores focus to the opening control", async () => {
    renderPanel();
    const dialog = selectAndOpen();
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Review approval confirmation" })).toHaveFocus());
  });
});
