import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CurrentPriceFreshness } from "./CurrentPriceFreshness";
describe("category-independent freshness", () => {
  it("keeps observation, successful check, availability and freshness separate", () => {
    render(<CurrentPriceFreshness data={{ observedAt: "2026-09-01T12:00:00Z", successfullyCheckedAt: "2026-10-01T12:00:00Z", availability: "no_listing", freshness: "stale" }} />);
    expect(screen.getByText(/Price observed/)).toHaveTextContent("2026-09-01");
    expect(screen.getByText(/Successfully checked/)).toHaveTextContent("2026-10-01");
    expect(screen.getByText(/Stale source data/)).toHaveTextContent("No listing");
  });
  it("does not infer fresh or listed from an observation alone", () => {
    render(<CurrentPriceFreshness data={{ observedAt: "2026-10-01T12:00:00Z" }} />);
    expect(screen.getByText("Freshness not confirmed")).toBeInTheDocument();
    expect(screen.getByText("Successful check time not reported")).toBeInTheDocument();
    expect(screen.queryByText(/Listed/)).not.toBeInTheDocument();
  });
  it("handles invalid and missing timestamps as unknown", () => {
    render(<CurrentPriceFreshness data={{ observedAt: "invalid", successfullyCheckedAt: null }} />);
    expect(screen.getByText("Price observation time unknown")).toBeInTheDocument();
  });
});
