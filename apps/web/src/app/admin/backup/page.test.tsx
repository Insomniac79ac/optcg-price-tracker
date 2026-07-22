import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const getAdminToken = vi.fn();
const createBackupExportJob = vi.fn();
const downloadBackup = vi.fn();
const fetchFileJob = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getAdminToken: (...args: unknown[]) => getAdminToken(...args),
    createBackupExportJob: (...args: unknown[]) => createBackupExportJob(...args),
    downloadBackup: (...args: unknown[]) => downloadBackup(...args),
    fetchFileJob: (...args: unknown[]) => fetchFileJob(...args),
  };
});

import AdminBackupPage from "./page";

describe("AdminBackupPage background export", () => {
  beforeEach(() => {
    getAdminToken.mockReset();
    getAdminToken.mockReturnValue("test-token");
    createBackupExportJob.mockReset();
    downloadBackup.mockReset();
    fetchFileJob.mockReset();
  });

  it("renders the background export button", () => {
    render(<AdminBackupPage />);
    expect(screen.getByRole("button", { name: "Prepare backup in background" })).toBeInTheDocument();
  });

  it("creates a background export job and shows the file job tracker", async () => {
    createBackupExportJob.mockResolvedValue({ file_job_id: 9, status: "queued" });
    fetchFileJob.mockResolvedValue({
      id: 9,
      job_type: "backup_export",
      status: "success",
      original_filename: null,
      output_filename: "opcg_backup_20260719.json",
      content_type: "application/json",
      dry_run: false,
      mode: null,
      progress_current: 0,
      progress_total: null,
      download_ready: true,
      summary: { size_bytes: 2048 },
      errors: null,
      warnings: null,
      started_at: "2026-07-19T12:00:00Z",
      finished_at: "2026-07-19T12:00:01Z",
      created_at: "2026-07-19T12:00:00Z",
      updated_at: "2026-07-19T12:00:01Z",
    });

    render(<AdminBackupPage />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare backup in background" }));

    await waitFor(() => expect(createBackupExportJob).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("File job #9")).toBeInTheDocument());
  });

  it("shows an error state when job creation fails", async () => {
    createBackupExportJob.mockRejectedValue(new Error("failed to queue"));
    render(<AdminBackupPage />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare backup in background" }));

    await waitFor(() => expect(screen.getByText("failed to queue")).toBeInTheDocument());
  });
});
