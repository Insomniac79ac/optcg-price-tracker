import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminNotFoundError } from "@/lib/api";

let routeId = "1127";
let detailSearch = new URLSearchParams();

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "admin@example.com" } }, status: "authenticated" }),
  signIn: vi.fn(), signOut: vi.fn(), getSession: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: routeId }),
  useSearchParams: () => detailSearch,
  usePathname: () => `/admin/source-mapping-proposals/${routeId}`,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const fetchProposalReviewGroup = vi.fn();
vi.mock("@/lib/proposalReview", async () => {
  const actual = await vi.importActual<typeof import("@/lib/proposalReview")>("@/lib/proposalReview");
  return { ...actual, fetchProposalReviewGroup: (...args: unknown[]) => fetchProposalReviewGroup(...args) };
});

import ProposalReviewDetailPage from "./page";
import { makeAlternative, makeReviewDetail } from "../proposalReview.fixtures";

describe("ProposalReviewDetailPage", () => {
  beforeEach(() => {
    routeId = "1127";
    detailSearch = new URLSearchParams();
    fetchProposalReviewGroup.mockReset().mockResolvedValue(makeReviewDetail());
  });

  it("loads a direct proposal URL and renders complete enriched evidence", async () => {
    render(<ProposalReviewDetailPage />);
    await waitFor(() => expect(fetchProposalReviewGroup).toHaveBeenCalledWith(1127, expect.any(AbortSignal)));
    expect(await screen.findByRole("heading", { name: "Proposal #1127" })).toBeInTheDocument();
    for (const heading of ["Source evidence", "Canonical identity", "Authoritative release", "Proposed printings (1)", "Resolver reasoning", "Historical state"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("Release membership is authoritative from CardPrint.release_product_id.")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Approve exact proposal" })).toBeInTheDocument();
    expect(screen.getByText("Eligible for exact-approval review")).toBeInTheDocument();
  });

  it("renders every ambiguous alternative with uncropped artwork and evidence", async () => {
    const second = makeAlternative({ alternative_id: 9002, card_print_id: 502, recommended: false, official_asset_variant: "p3", printing_label: "Second parallel", display_image: null, canonical_image_url: null, image_missing: true, missing_evidence: ["Listing photo does not distinguish the treatment"] });
    fetchProposalReviewGroup.mockResolvedValue(makeReviewDetail({ resolution_status: "ambiguous", alternatives: [makeAlternative({ recommended: false }), second], recommended_print: null, recommended_alternative_count: 0, alternative_count: 2 }));
    render(<ProposalReviewDetailPage />);
    expect(await screen.findByRole("heading", { name: "Proposed printings (2)" })).toBeInTheDocument();
    expect(screen.getByText(/CardPrint #501/)).toBeInTheDocument();
    expect(screen.getByText(/CardPrint #502/)).toBeInTheDocument();
    expect(screen.getByText("Listing photo does not distinguish the treatment")).toBeInTheDocument();
    const images = (screen.getAllByRole("img") as HTMLImageElement[]).filter((image) => image.alt.includes("artwork"));
    expect(images.every((image) => image.className.includes("object-contain"))).toBe(true);
    expect(screen.getAllByText("Artwork unavailable").length).toBeGreaterThan(0);
  });

  it("keeps compatibility metadata collapsed and explicitly subordinate", async () => {
    render(<ProposalReviewDetailPage />);
    expect(await screen.findByText("Legacy compatibility metadata")).toBeInTheDocument();
    expect(screen.getByText("This metadata is retained for older collection and compatibility paths. It is not authoritative pricing identity.")).toBeInTheDocument();
    expect(screen.getByText("Legacy Card/card_id compatibility only")).toBeInTheDocument();
  });

  it("does not load an external candidate image and marks safe external links", async () => {
    render(<ProposalReviewDetailPage />);
    await screen.findByRole("heading", { name: "Source evidence" });
    const images = (screen.getAllByRole("img") as HTMLImageElement[]).filter((image) => image.alt.includes("artwork"));
    expect(images.some((image) => image.src.includes("yuyu-tei"))).toBe(false);
    expect(images.every((image) => !image.src.startsWith("https://www.onepiece-cardgame.com"))).toBe(true);
    const sourceLinks = screen.getAllByRole("link", { name: /opens in a new tab/ });
    expect(sourceLinks.length).toBeGreaterThan(0);
    for (const link of sourceLinks) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noreferrer");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });

  it("does not hotlink a non-owned marketplace display image", async () => {
    const alternative = makeAlternative({
      display_image: {
        url: "https://card.yuyu-tei.jp/card_image/opc/front/9911.jpg",
        source: "yuyutei",
        exact_print_verified: true,
        owned_asset_selected: false,
        geometry: null,
      },
    });
    fetchProposalReviewGroup.mockResolvedValue(makeReviewDetail({ alternatives: [alternative] }));
    render(<ProposalReviewDetailPage />);
    await screen.findByRole("heading", { name: "Approve exact proposal" });
    const artwork = (screen.getAllByRole("img") as HTMLImageElement[]).filter((image) => image.alt.includes("artwork"));
    expect(artwork.length).toBeGreaterThan(0);
    expect(artwork.every((image) => !image.src.includes("yuyu-tei"))).toBe(true);
    expect(artwork.every((image) => image.getAttribute("src")?.startsWith("/api/card-image?u="))).toBe(true);
  });

  it("preserves the exact filtered queue return URL", async () => {
    detailSearch = new URLSearchParams({ returnTo: "/admin/source-mapping-proposals?source=snkrdunk&page=4&limit=25" });
    render(<ProposalReviewDetailPage />);
    const returnLink = await screen.findByRole("link", { name: "← Return to filtered queue" });
    expect(returnLink).toHaveAttribute("href", "/admin/source-mapping-proposals?source=snkrdunk&page=4&limit=25");
  });

  it("renders an explicit missing-image state", async () => {
    const detail = makeReviewDetail();
    detail.candidate = { ...detail.candidate, image_url: null, image_missing: true };
    detail.alternatives = [makeAlternative({ display_image: null, canonical_image_url: null, image_missing: true })];
    fetchProposalReviewGroup.mockResolvedValue(detail);
    render(<ProposalReviewDetailPage />);
    expect(await screen.findByText("Candidate artwork is missing.")).toBeInTheDocument();
    expect(screen.getAllByText("Artwork unavailable").length).toBeGreaterThan(0);
  });

  it("renders a proposal detail 404", async () => {
    fetchProposalReviewGroup.mockRejectedValue(new AdminNotFoundError());
    render(<ProposalReviewDetailPage />);
    expect(await screen.findByText("Proposal #1127 was not found.")).toBeInTheDocument();
  });

  it("places the approval entry point only after the complete resolver evidence", async () => {
    render(<ProposalReviewDetailPage />);
    const reasoning = await screen.findByRole("heading", { name: "Resolver reasoning" });
    const approval = screen.getByRole("heading", { name: "Approve exact proposal" });
    expect(reasoning.compareDocumentPosition(approval) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const label of ["Reject", "Mark reviewed", "Create mapping", "Replace printing"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });
});
