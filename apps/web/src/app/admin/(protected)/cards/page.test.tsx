import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminCardListResponse, CardCatalogImportResponse } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchAdminCards = vi.fn();
const importCardsCsv = vi.fn();
const downloadCardsCsv = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchAdminCards: (...args: unknown[]) => fetchAdminCards(...args),
    importCardsCsv: (...args: unknown[]) => importCardsCsv(...args),
    downloadCardsCsv: (...args: unknown[]) => downloadCardsCsv(...args),
  };
});

import AdminCardsPage from "./page";

const EMPTY_LIST: AdminCardListResponse = {
  summary: { total_cards: 0, missing_metadata_count: 0, by_set: {}, by_rarity: {} },
  cards: [],
  pagination: {
    total: 0,
    limit: 100,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

const LIST_WITH_ROWS: AdminCardListResponse = {
  summary: { total_cards: 1, missing_metadata_count: 1, by_set: { OP01: 1 }, by_rarity: { L: 1 } },
  cards: [
    {
      id: 1,
      card_code: "OP01-001",
      name_en: "Monkey D. Luffy",
      name_jp: null,
      set_code: "OP01",
      rarity: "L",
      variant: null,
      language: "en",
      image_url: null,
      release_date: null,
      artist: null,
      character: null,
      color: null,
      card_type: null,
      cost: null,
      power: null,
      counter: null,
      attribute: null,
      effect_text: null,
      trigger_text: null,
      notes: null,
      created_at: "2026-07-20T09:00:00Z",
      updated_at: "2026-07-20T09:00:00Z",
    },
  ],
  pagination: { ...EMPTY_LIST.pagination, total: 1 },
};

function makeCsvFile(): File {
  return new File(["card_code,name_en\nOP01-001,Luffy\n"], "cards.csv", { type: "text/csv" });
}

describe("AdminCardsPage", () => {
  beforeEach(() => {
    fetchAdminCards.mockReset();
    importCardsCsv.mockReset();
    downloadCardsCsv.mockReset();
  });

  it("renders an empty card list without crashing", async () => {
    fetchAdminCards.mockResolvedValue(EMPTY_LIST);
    render(<AdminCardsPage />);

    await waitFor(() =>
      expect(screen.getByText("No cards match the current filters.")).toBeInTheDocument(),
    );
  });

  it("renders the card table when cards are present", async () => {
    fetchAdminCards.mockResolvedValue(LIST_WITH_ROWS);
    render(<AdminCardsPage />);

    await waitFor(() => expect(screen.getByText("OP01-001")).toBeInTheDocument());
    expect(screen.getByText("Monkey D. Luffy")).toBeInTheDocument();
  });

  it("calls downloadCardsCsv when the export button is clicked", async () => {
    fetchAdminCards.mockResolvedValue(EMPTY_LIST);
    downloadCardsCsv.mockResolvedValue(undefined);
    render(<AdminCardsPage />);

    await waitFor(() => expect(fetchAdminCards).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Export cards CSV" }));

    await waitFor(() => expect(downloadCardsCsv).toHaveBeenCalled());
  });

  it("renders the import preview after a dry-run import", async () => {
    fetchAdminCards.mockResolvedValue(EMPTY_LIST);
    const result: CardCatalogImportResponse = {
      dry_run: true,
      overwrite: false,
      summary: { total_rows: 1, valid_rows: 1, error_rows: 0, created: 1, updated: 0, skipped: 0 },
      errors: [],
      preview: [
        {
          row_number: 2,
          card_code: "OP01-001",
          action: "would_create",
          changes: { name_en: { old: null, new: "Luffy" } },
        },
      ],
    };
    importCardsCsv.mockResolvedValue(result);
    render(<AdminCardsPage />);

    await waitFor(() => expect(fetchAdminCards).toHaveBeenCalled());

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeCsvFile()] } });

    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));

    await waitFor(() => expect(screen.getByText("would_create")).toBeInTheDocument());
    expect(screen.getByText("name_en")).toBeInTheDocument();
  });

  it("renders import row errors", async () => {
    fetchAdminCards.mockResolvedValue(EMPTY_LIST);
    const result: CardCatalogImportResponse = {
      dry_run: true,
      overwrite: false,
      summary: { total_rows: 1, valid_rows: 0, error_rows: 1, created: 0, updated: 0, skipped: 0 },
      errors: [{ row_number: 2, card_code: null, error: "card_code is required" }],
      preview: [],
    };
    importCardsCsv.mockResolvedValue(result);
    render(<AdminCardsPage />);

    await waitFor(() => expect(fetchAdminCards).toHaveBeenCalled());

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeCsvFile()] } });

    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));

    await waitFor(() => expect(screen.getByText("card_code is required")).toBeInTheDocument());
  });

  it("requires typing IMPORT to confirm before a real (non-dry-run) import runs", async () => {
    fetchAdminCards.mockResolvedValue(EMPTY_LIST);
    const result: CardCatalogImportResponse = {
      dry_run: false,
      overwrite: false,
      summary: { total_rows: 1, valid_rows: 1, error_rows: 0, created: 1, updated: 0, skipped: 0 },
      errors: [],
      preview: [],
    };
    importCardsCsv.mockResolvedValue(result);
    render(<AdminCardsPage />);

    await waitFor(() => expect(fetchAdminCards).toHaveBeenCalled());

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeCsvFile()] } });

    fireEvent.click(screen.getByLabelText("Dry run"));
    fireEvent.click(screen.getByRole("button", { name: "Import for real" }));

    // Modal is open, but confirm is disabled until "IMPORT" is typed.
    expect(screen.getByText("Import card catalog for real")).toBeInTheDocument();
    expect(importCardsCsv).not.toHaveBeenCalled();

    const confirmButtons = screen.getAllByRole("button", { name: "Import for real" });
    const modalConfirmButton = confirmButtons[confirmButtons.length - 1];
    expect(modalConfirmButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Type IMPORT to confirm"), {
      target: { value: "IMPORT" },
    });
    expect(modalConfirmButton).not.toBeDisabled();

    fireEvent.click(modalConfirmButton);

    await waitFor(() => expect(importCardsCsv).toHaveBeenCalledWith(expect.anything(), { dryRun: false, overwrite: false }));
  });
});
