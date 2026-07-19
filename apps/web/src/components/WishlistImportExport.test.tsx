import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const downloadWishlistCsv = vi.fn();
const importWishlistCsv = vi.fn();
const importWishlistCsvBackground = vi.fn();
const createWishlistExportJob = vi.fn();
const fetchFileJob = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    downloadWishlistCsv: (...args: unknown[]) => downloadWishlistCsv(...args),
    importWishlistCsv: (...args: unknown[]) => importWishlistCsv(...args),
    importWishlistCsvBackground: (...args: unknown[]) => importWishlistCsvBackground(...args),
    createWishlistExportJob: (...args: unknown[]) => createWishlistExportJob(...args),
    fetchFileJob: (...args: unknown[]) => fetchFileJob(...args),
  };
});

import { WishlistImportExport } from "./WishlistImportExport";

function makeFile(text: string, name = "wishlist.csv") {
  return new File([text], name, { type: "text/csv" });
}

describe("WishlistImportExport", () => {
  beforeEach(() => {
    downloadWishlistCsv.mockReset();
    importWishlistCsv.mockReset();
    importWishlistCsvBackground.mockReset();
    createWishlistExportJob.mockReset();
    fetchFileJob.mockReset();
  });

  it("renders the background import toggle and prepare-export button", () => {
    render(<WishlistImportExport onImported={vi.fn()} />);
    expect(screen.getByText("Run import in background")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare wishlist export" })).toBeInTheDocument();
  });

  it("calls importWishlistCsvBackground when background is checked", async () => {
    importWishlistCsvBackground.mockResolvedValue({ file_job_id: 5, status: "queued" });
    fetchFileJob.mockResolvedValue({
      id: 5,
      job_type: "wishlist_import",
      status: "success",
      original_filename: "wishlist.csv",
      output_filename: null,
      content_type: null,
      dry_run: true,
      mode: "upsert",
      progress_current: 1,
      progress_total: 1,
      download_ready: false,
      summary: { created: 1 },
      errors: null,
      warnings: null,
      started_at: null,
      finished_at: "2026-07-19T12:00:01Z",
      created_at: "2026-07-19T12:00:00Z",
      updated_at: "2026-07-19T12:00:01Z",
    });

    render(<WishlistImportExport onImported={vi.fn()} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeFile("card_code\nOP01-001\n")] } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Run import in background" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));

    await waitFor(() =>
      expect(importWishlistCsvBackground).toHaveBeenCalledWith(expect.any(File), {
        dryRun: true,
        mode: "upsert",
      }),
    );
    await waitFor(() => expect(screen.getByText("File job #5")).toBeInTheDocument());
  });

  it("does not crash when export job creation fails", async () => {
    createWishlistExportJob.mockRejectedValue(new Error("nope"));
    render(<WishlistImportExport onImported={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare wishlist export" }));

    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());
  });
});
