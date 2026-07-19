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

const downloadCollectionCsv = vi.fn();
const importCollectionCsv = vi.fn();
const importCollectionCsvBackground = vi.fn();
const createCollectionExportJob = vi.fn();
const fetchFileJob = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    downloadCollectionCsv: (...args: unknown[]) => downloadCollectionCsv(...args),
    importCollectionCsv: (...args: unknown[]) => importCollectionCsv(...args),
    importCollectionCsvBackground: (...args: unknown[]) => importCollectionCsvBackground(...args),
    createCollectionExportJob: (...args: unknown[]) => createCollectionExportJob(...args),
    fetchFileJob: (...args: unknown[]) => fetchFileJob(...args),
  };
});

import { CollectionImportExport } from "./CollectionImportExport";

function makeFile(text: string, name = "collection.csv") {
  return new File([text], name, { type: "text/csv" });
}

const SUCCESS_JOB = {
  id: 42,
  job_type: "collection_import",
  status: "success",
  original_filename: "collection.csv",
  output_filename: null,
  content_type: null,
  dry_run: false,
  mode: "upsert",
  progress_current: 3,
  progress_total: 3,
  download_ready: false,
  summary: { created: 3 },
  errors: null,
  warnings: null,
  started_at: "2026-07-19T12:00:00Z",
  finished_at: "2026-07-19T12:00:01Z",
  created_at: "2026-07-19T12:00:00Z",
  updated_at: "2026-07-19T12:00:01Z",
};

describe("CollectionImportExport", () => {
  beforeEach(() => {
    downloadCollectionCsv.mockReset();
    importCollectionCsv.mockReset();
    importCollectionCsvBackground.mockReset();
    createCollectionExportJob.mockReset();
    fetchFileJob.mockReset();
  });

  it("renders the background import toggle and prepare-export button", () => {
    render(<CollectionImportExport onImported={vi.fn()} />);
    expect(screen.getByText("Run import in background")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare collection export" })).toBeInTheDocument();
  });

  it("calls importCollectionCsvBackground and shows the file job tracker when background is checked", async () => {
    importCollectionCsvBackground.mockResolvedValue({ file_job_id: 42, status: "queued" });
    fetchFileJob.mockResolvedValue(SUCCESS_JOB);
    const onImported = vi.fn();

    render(<CollectionImportExport onImported={onImported} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeFile("card_code,quantity\nOP01-001,1\n")] } });

    fireEvent.click(screen.getByRole("checkbox", { name: "Run import in background" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Dry run" })); // uncheck dry run
    fireEvent.click(screen.getByRole("button", { name: "Import for real" }));

    await waitFor(() =>
      expect(importCollectionCsvBackground).toHaveBeenCalledWith(expect.any(File), {
        dryRun: false,
        mode: "upsert",
      }),
    );

    await waitFor(() => expect(screen.getByText("File job #42")).toBeInTheDocument());
    await waitFor(() => expect(onImported).toHaveBeenCalled());
  });

  it("calls createCollectionExportJob when 'Prepare collection export' is clicked", async () => {
    createCollectionExportJob.mockResolvedValue({ file_job_id: 7, status: "queued" });
    fetchFileJob.mockResolvedValue({ ...SUCCESS_JOB, id: 7, job_type: "collection_export", download_ready: true });

    render(<CollectionImportExport onImported={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare collection export" }));

    await waitFor(() => expect(createCollectionExportJob).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("File job #7")).toBeInTheDocument());
  });

  it("shows an error state when the background import request fails", async () => {
    importCollectionCsvBackground.mockRejectedValue(new Error("upload failed"));

    render(<CollectionImportExport onImported={vi.fn()} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeFile("card_code,quantity\nOP01-001,1\n")] } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Run import in background" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));

    await waitFor(() => expect(screen.getByText("upload failed")).toBeInTheDocument());
  });
});
