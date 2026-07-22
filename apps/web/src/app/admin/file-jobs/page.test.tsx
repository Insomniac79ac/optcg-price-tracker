import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const fetchFileJobs = vi.fn();
const cancelFileJob = vi.fn();
const downloadFileJob = vi.fn();
const cleanupFileJobs = vi.fn();
const getAdminToken = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchFileJobs: (...args: unknown[]) => fetchFileJobs(...args),
    cancelFileJob: (...args: unknown[]) => cancelFileJob(...args),
    downloadFileJob: (...args: unknown[]) => downloadFileJob(...args),
    cleanupFileJobs: (...args: unknown[]) => cleanupFileJobs(...args),
    getAdminToken: (...args: unknown[]) => getAdminToken(...args),
  };
});

import FileJobsPage from "./page";

const SAMPLE_JOB = {
  id: 1,
  job_type: "collection_export",
  status: "success",
  original_filename: null,
  output_filename: "collection_export_20260719.csv",
  content_type: "text/csv",
  dry_run: false,
  mode: null,
  progress_current: 0,
  progress_total: null,
  download_ready: true,
  summary: { size_bytes: 1024 },
  errors: null,
  warnings: null,
  started_at: "2026-07-19T12:00:00Z",
  finished_at: "2026-07-19T12:00:05Z",
  created_at: "2026-07-19T12:00:00Z",
  updated_at: "2026-07-19T12:00:05Z",
};

const EMPTY_PAGINATION = {
  total: 0,
  limit: 50,
  offset: 0,
  has_next: false,
  has_previous: false,
  next_offset: null,
  previous_offset: null,
};

describe("FileJobsPage", () => {
  beforeEach(() => {
    fetchFileJobs.mockReset();
    cancelFileJob.mockReset();
    downloadFileJob.mockReset();
    cleanupFileJobs.mockReset();
    getAdminToken.mockReset();
    getAdminToken.mockReturnValue("test-token");
  });

  it("does not crash and shows an empty state when there are no jobs", async () => {
    fetchFileJobs.mockResolvedValue({ jobs: [], total: 0, limit: 50, offset: 0, pagination: EMPTY_PAGINATION });
    render(<FileJobsPage />);

    await waitFor(() => expect(screen.getByText("No file jobs found.")).toBeInTheDocument());
  });

  it("renders jobs returned by the API", async () => {
    fetchFileJobs.mockResolvedValue({
      jobs: [SAMPLE_JOB],
      total: 1,
      limit: 50,
      offset: 0,
      pagination: { ...EMPTY_PAGINATION, total: 1 },
    });
    render(<FileJobsPage />);

    await waitFor(() => expect(screen.getAllByText("collection_export").length).toBeGreaterThan(0));
    const row = screen.getAllByText("collection_export").find((el) => el.closest("tr"))!.closest("tr")!;
    expect(within(row).getByText("success")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Download" })).toBeInTheDocument();
  });

  it("renders an error state when the list request fails", async () => {
    fetchFileJobs.mockRejectedValue(new Error("boom"));
    render(<FileJobsPage />);

    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
  });

  it("does not call cleanupFileJobs until CLEANUP is typed to confirm", async () => {
    fetchFileJobs.mockResolvedValue({ jobs: [], total: 0, limit: 50, offset: 0, pagination: EMPTY_PAGINATION });
    render(<FileJobsPage />);

    await waitFor(() => expect(screen.getByText("No file jobs found.")).toBeInTheDocument());

    // Dry run is checked by default, so toggle it off to reach the confirm gate.
    fireEvent.click(screen.getByRole("checkbox", { name: /dry run/i }));
    fireEvent.click(screen.getByRole("button", { name: "Run cleanup" }));
    expect(cleanupFileJobs).not.toHaveBeenCalled();
    expect(screen.getByText("Type CLEANUP to confirm a real cleanup.")).toBeInTheDocument();

    const confirmInput = screen.getByRole("textbox", { name: /type cleanup to confirm/i });
    fireEvent.change(confirmInput, { target: { value: "CLEANUP" } });

    cleanupFileJobs.mockResolvedValue({ dry_run: false, older_than_days: 7, would_delete: 2, deleted: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Run cleanup" }));

    await waitFor(() =>
      expect(cleanupFileJobs).toHaveBeenCalledWith({
        older_than_days: 7,
        dry_run: false,
        confirm: "CLEANUP",
      }),
    );
  });

  it("cancels a running job and refetches the list", async () => {
    const runningJob = { ...SAMPLE_JOB, status: "running", download_ready: false };
    fetchFileJobs.mockResolvedValue({
      jobs: [runningJob],
      total: 1,
      limit: 50,
      offset: 0,
      pagination: { ...EMPTY_PAGINATION, total: 1 },
    });
    cancelFileJob.mockResolvedValue({ id: 1, status: "cancelled" });

    render(<FileJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(cancelFileJob).toHaveBeenCalledWith(1));
    await waitFor(() => expect(fetchFileJobs).toHaveBeenCalledTimes(2));
  });
});
