import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAuthRequiredError } from "@/lib/api";

let currentSearch = new URLSearchParams();
const replace = vi.fn();
const router = { push: vi.fn(), replace };

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "admin@example.com" } }, status: "authenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  getSession: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/admin/source-mapping-proposals",
  useSearchParams: () => currentSearch,
}));

const fetchProposalReviewSummary = vi.fn();
const fetchProposalReviewReleases = vi.fn();
const fetchProposalReviewGroups = vi.fn();
vi.mock("@/lib/proposalReview", async () => {
  const actual = await vi.importActual<typeof import("@/lib/proposalReview")>("@/lib/proposalReview");
  return {
    ...actual,
    fetchProposalReviewSummary: (...args: unknown[]) => fetchProposalReviewSummary(...args),
    fetchProposalReviewReleases: (...args: unknown[]) => fetchProposalReviewReleases(...args),
    fetchProposalReviewGroups: (...args: unknown[]) => fetchProposalReviewGroups(...args),
  };
});

import ProposalReviewPage from "./page";
import {
  REVIEW_RELEASES,
  REVIEW_SUMMARY,
  makeGroupList,
  makeReviewGroup,
} from "./proposalReview.fixtures";

function renderPage(search = "") {
  currentSearch = new URLSearchParams(search);
  return render(<ProposalReviewPage />);
}

describe("ProposalReviewPage", () => {
  beforeEach(() => {
    currentSearch = new URLSearchParams();
    replace.mockReset();
    fetchProposalReviewSummary.mockReset().mockResolvedValue(REVIEW_SUMMARY);
    fetchProposalReviewReleases.mockReset().mockResolvedValue(REVIEW_RELEASES);
    fetchProposalReviewGroups.mockReset().mockResolvedValue(makeGroupList());
  });

  it("renders the accepted 4,027 queue summary and read-only framing", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("4,027")).toBeInTheDocument());
    expect(screen.getAllByText("1,918").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1,866").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Read-only queue").length).toBeGreaterThan(0);
    expect(screen.getByText("Approval is available only from an eligible proposal detail page. Queue rows remain read-only.")).toBeInTheDocument();
  });

  it("updates URL-backed source and resolution filters and resets the page", async () => {
    renderPage("page=3");
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Yuyu \(3,553\)/ }));
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ source: "yuyutei", offset: 0 })));
    expect(replace.mock.calls.at(-1)?.[0]).toContain("source=yuyutei");
    expect(replace.mock.calls.at(-1)?.[0]).not.toContain("page=");
    fireEvent.click(screen.getByRole("button", { name: /Ambiguous \(1,866\)/ }));
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ resolution_status: "ambiguous" })));
    expect(replace.mock.calls.at(-1)?.[0]).toContain("resolution=ambiguous");
  });

  it("keeps authoritative and unresolved release filters distinct", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Authoritative release" })).toBeInTheDocument());
    const release = screen.getByRole("combobox", { name: "Authoritative release" });
    fireEvent.change(release, { target: { value: "17" } });
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ release_product_id: 17, unresolved_release: undefined })));
    expect(replace.mock.calls.at(-1)?.[0]).toContain("release=17");
    fireEvent.change(release, { target: { value: "unresolved" } });
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ release_product_id: undefined, unresolved_release: true })));
    expect(replace.mock.calls.at(-1)?.[0]).toContain("unresolvedRelease=true");
  });

  it("debounces search and paginates through URL state", async () => {
    fetchProposalReviewGroups.mockResolvedValue(makeGroupList([makeReviewGroup()], 100));
    renderPage();
    await waitFor(() => expect(screen.getByText(/1–50 of 100/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("searchbox", { name: "Search proposals" }), { target: { value: "zoro" } });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 400)); });
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ q: "zoro" })));
    expect(replace.mock.calls.some(([href]) => String(href).includes("q=zoro"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })));
    expect(replace.mock.calls.at(-1)?.[0]).toContain("page=2");
  });

  it("recovers invalid URL values safely", async () => {
    renderPage("source=other&resolution=magic&page=nope&limit=500");
    await waitFor(() => expect(fetchProposalReviewGroups).toHaveBeenCalledWith(expect.objectContaining({ source: undefined, resolution_status: undefined, limit: 50, offset: 0 })));
    expect(replace).toHaveBeenCalledWith("/admin/source-mapping-proposals", { scroll: false });
  });

  it("renders exact, ambiguous, identity-unresolved, and release-unresolved language", async () => {
    const exact = makeReviewGroup();
    const ambiguous = makeReviewGroup({ id: 1501, resolution_status: "ambiguous", alternative_count: 3, recommended_alternative_count: 0, recommended_print: null });
    const identity = makeReviewGroup({ id: 1710, resolution_status: "unresolved_identity", canonical_card: null, canonical_card_id: null, card_code: null, name_en: null, name_jp: null, recommended_print: null, alternative_count: 0, recommended_alternative_count: 0 });
    const releaseUnresolved = makeReviewGroup({ id: 5131, source_name: "snkrdunk", source: { id: 2, name: "snkrdunk" }, resolution_status: "release_unresolved", release: null, release_product_id: null, recommended_print: null });
    fetchProposalReviewGroups.mockResolvedValue(makeGroupList([exact, ambiguous, identity, releaseUnresolved]));
    renderPage();
    await waitFor(() => expect(screen.getAllByText("Exact proposal").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Ambiguous — multiple printings").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Identity unresolved").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Release unresolved").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/3 possible printings/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("No canonical card family was established.").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no release is inferred from the card code/i).length).toBeGreaterThan(0);
  });

  it("uses uncropped exact-print artwork and never loads candidate marketplace images", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByRole("img").length).toBeGreaterThan(0));
    const images = (screen.getAllByRole("img") as HTMLImageElement[]).filter((image) => image.alt.includes("artwork"));
    expect(images.every((image) => image.className.includes("object-contain"))).toBe(true);
    expect(images.some((image) => image.src.includes("yuyu-tei"))).toBe(false);
    expect(screen.queryAllByText(/Candidate artwork missing/).length).toBe(0);
  });

  it("renders empty, error, and unauthorized states", async () => {
    fetchProposalReviewGroups.mockResolvedValueOnce(makeGroupList([]));
    const first = renderPage();
    await waitFor(() => expect(screen.getByText("No proposals match these filters.")).toBeInTheDocument());
    first.unmount();

    fetchProposalReviewGroups.mockRejectedValueOnce(new Error("backend unavailable"));
    const second = renderPage();
    await waitFor(() => expect(screen.getByText("backend unavailable")).toBeInTheDocument());
    second.unmount();

    fetchProposalReviewGroups.mockRejectedValueOnce(new AdminAuthRequiredError());
    renderPage();
    await waitFor(() => expect(screen.getByText(/admin session has expired/i)).toBeInTheDocument());
  });

  it("contains detail links but no proposal mutation controls", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Review evidence for proposal 1127/ }).length).toBeGreaterThan(0));
    for (const label of ["Approve", "Reject", "Mark reviewed", "Create mapping", "Replace printing"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });
});
