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

const getAdminToken = vi.fn();
const fetchImportTemplates = vi.fn();
const downloadImportTemplate = vi.fn();
const validateImportCsv = vi.fn();
const fetchImportValidationReports = vi.fn();
const fetchImportValidationReport = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getAdminToken: (...args: unknown[]) => getAdminToken(...args),
    fetchImportTemplates: (...args: unknown[]) => fetchImportTemplates(...args),
    downloadImportTemplate: (...args: unknown[]) => downloadImportTemplate(...args),
    validateImportCsv: (...args: unknown[]) => validateImportCsv(...args),
    fetchImportValidationReports: (...args: unknown[]) => fetchImportValidationReports(...args),
    fetchImportValidationReport: (...args: unknown[]) => fetchImportValidationReport(...args),
  };
});

import AdminImportValidationPage from "./page";

const TEMPLATES = [
  {
    template_type: "card_catalog",
    filename: "card_catalog_template.csv",
    description: "Canonical card catalog rows.",
    required_columns: ["card_code", "name_en"],
    optional_columns: ["name_jp", "set_code"],
    download_url: "/admin/import-templates/card_catalog.csv",
    notes: [],
  },
  {
    template_type: "source_mappings",
    filename: "source_mappings_template.csv",
    description: "Links a card_code to a listing.",
    required_columns: ["source_name", "source_url", "card_code"],
    optional_columns: [],
    download_url: "/admin/import-templates/source_mappings.csv",
    notes: [],
  },
  {
    template_type: "snkrdunk_candidates",
    filename: "snkrdunk_candidates_template.csv",
    description: "Manually collected SNKRDUNK listing candidates.",
    required_columns: ["source_url", "title"],
    optional_columns: [],
    download_url: "/admin/import-templates/snkrdunk_candidates.csv",
    notes: [],
  },
  {
    template_type: "collection",
    filename: "collection_template.csv",
    description: "Personal collection items.",
    required_columns: ["card_code", "quantity"],
    optional_columns: [],
    download_url: "/admin/import-templates/collection.csv",
    notes: [],
  },
  {
    template_type: "wishlist",
    filename: "wishlist_template.csv",
    description: "Wishlist items.",
    required_columns: ["card_code"],
    optional_columns: [],
    download_url: "/admin/import-templates/wishlist.csv",
    notes: [],
  },
];

const VALIDATION_RESULT = {
  import_type: "card_catalog",
  valid: false,
  summary: {
    total_rows: 2,
    valid_rows: 1,
    error_rows: 1,
    warning_rows: 1,
    duplicate_rows: 0,
    would_create: 1,
    would_update: 0,
    would_skip: 0,
  },
  columns: {
    required_columns: ["card_code", "name_en"],
    optional_columns: ["set_code"],
    received_columns: ["card_code", "name_en"],
    missing_required_columns: [],
    unknown_columns: [],
  },
  errors: [
    { row_number: 2, field: "card_code", value: "", code: "required_field_missing", message: "card_code is required" },
  ],
  warnings: [
    { row_number: 3, field: "variant", value: "para", code: "normalized_value", message: "variant will be normalized to parallel" },
  ],
  preview: [
    {
      row_number: 3,
      action: "would_create" as const,
      normalized_values: { card_code: "OP01-001" },
      warnings: ["variant will be normalized to parallel"],
      errors: [],
    },
  ],
};

function makeFile(name = "cards.csv"): File {
  return new File(["card_code,name_en\nOP01-001,Luffy\n"], name, { type: "text/csv" });
}

describe("AdminImportValidationPage", () => {
  beforeEach(() => {
    getAdminToken.mockReset();
    getAdminToken.mockReturnValue("test-token");
    fetchImportTemplates.mockReset();
    fetchImportTemplates.mockResolvedValue({ templates: TEMPLATES });
    downloadImportTemplate.mockReset();
    downloadImportTemplate.mockResolvedValue(undefined);
    validateImportCsv.mockReset();
    fetchImportValidationReports.mockReset();
    fetchImportValidationReports.mockResolvedValue({
      reports: [],
      pagination: { total: 0, limit: 25, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
    });
    fetchImportValidationReport.mockReset();
  });

  it("renders the page header", async () => {
    render(<AdminImportValidationPage />);
    expect(screen.getByText("Import Validation")).toBeInTheDocument();
    await waitFor(() => expect(fetchImportTemplates).toHaveBeenCalled());
  });

  it("renders template cards with download buttons", async () => {
    render(<AdminImportValidationPage />);

    await waitFor(() => expect(screen.getByText("Card Catalog")).toBeInTheDocument());
    // "Source Mappings"/"Collection"/"Wishlist" etc. also appear as <option>
    // labels in the import-type <select>, so assert at least one match
    // rather than a single unique element.
    expect(screen.getAllByText("Source Mappings").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SNKRDUNK Candidates").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Collection").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Wishlist").length).toBeGreaterThan(0);

    const downloadButtons = screen.getAllByRole("button", { name: "Download CSV" });
    expect(downloadButtons).toHaveLength(5);

    fireEvent.click(downloadButtons[0]);
    await waitFor(() => expect(downloadImportTemplate).toHaveBeenCalledWith("card_catalog"));
  });

  it("renders the empty report history state without crashing", async () => {
    render(<AdminImportValidationPage />);
    await waitFor(() =>
      expect(screen.getByText("No import validation reports yet.")).toBeInTheDocument(),
    );
  });

  it("validates a file and renders errors/warnings/summary", async () => {
    validateImportCsv.mockResolvedValue(VALIDATION_RESULT);

    render(<AdminImportValidationPage />);
    await waitFor(() => expect(fetchImportTemplates).toHaveBeenCalled());

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeFile()] } });

    fireEvent.click(screen.getByRole("button", { name: "Validate" }));

    await waitFor(() => expect(validateImportCsv).toHaveBeenCalled());
    expect(screen.getByText("Invalid")).toBeInTheDocument();
    expect(screen.getByText("card_code is required")).toBeInTheDocument();
    // Appears in both the warnings table and the preview table's warnings column.
    expect(screen.getAllByText("variant will be normalized to parallel").length).toBeGreaterThan(0);
    expect(screen.getByText("required_field_missing")).toBeInTheDocument();
  });

  it("renders report history rows and expands a report detail", async () => {
    fetchImportValidationReports.mockResolvedValue({
      reports: [
        {
          id: 1,
          created_at: "2026-07-20T12:00:00Z",
          import_type: "card_catalog",
          filename: "cards.csv",
          valid: false,
          strict: false,
          total_rows: 2,
          valid_rows: 1,
          error_rows: 1,
          warning_rows: 1,
          duplicate_rows: 0,
        },
      ],
      pagination: { total: 1, limit: 25, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
    });
    fetchImportValidationReport.mockResolvedValue({
      id: 1,
      created_at: "2026-07-20T12:00:00Z",
      import_type: "card_catalog",
      filename: "cards.csv",
      valid: false,
      strict: false,
      total_rows: 2,
      valid_rows: 1,
      error_rows: 1,
      warning_rows: 1,
      duplicate_rows: 0,
      report_payload_json: VALIDATION_RESULT,
    });

    render(<AdminImportValidationPage />);

    await waitFor(() => expect(screen.getByText("cards.csv")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Open" }));

    await waitFor(() => expect(fetchImportValidationReport).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.getByText("card_code is required")).toBeInTheDocument());
  });
});
