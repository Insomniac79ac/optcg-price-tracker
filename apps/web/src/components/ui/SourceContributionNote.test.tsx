import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceConstraintNote } from "./SourceConstraintNote";
import { SourceContributionNote } from "./SourceContributionNote";

/** Both notes as the print panel actually stacks them, so the assertions are
 * about what a collector reads rather than about one component in isolation. */
function Panel(props: {
  eligible: boolean;
  constraint?: string | null;
  contributes_to_index?: boolean | null;
}) {
  return (
    <div>
      <SourceConstraintNote value={props} />
      <SourceContributionNote value={props} />
    </div>
  );
}

describe("SourceContributionNote", () => {
  it("marks an eligible, unconstrained price that did not feed the index", () => {
    render(<Panel eligible contributes_to_index={false} />);

    expect(screen.getByText("Reference only")).toBeInTheDocument();
    expect(
      screen.getByText("Shown for context; not used in Market Index."),
    ).toBeInTheDocument();
  });

  it("renders nothing for a price that did feed the index", () => {
    const { container } = render(<Panel eligible contributes_to_index={true} />);
    expect(container.textContent).toBe("");
  });

  // bool | None on the wire: absent means the API predates the field, and
  // reading that as an exclusion would badge every price an older API serves.
  it("renders nothing for an API that predates the field", () => {
    expect(render(<Panel eligible />).container.textContent).toBe("");
    expect(
      render(<Panel eligible contributes_to_index={null} />).container.textContent,
    ).toBe("");
  });

  // The two concepts stay separate but must not both speak. A platform-floor
  // price already has a specific reason on screen plus "Not used in Market
  // Index"; a second, vaguer badge would say less and repeat more.
  it("stays silent where a constraint has already stated the exclusion", () => {
    render(
      <Panel eligible={false} constraint="platform_floor" contributes_to_index={false} />,
    );

    expect(screen.getByText("Minimum listing price")).toBeInTheDocument();
    expect(screen.getByText("Not used in Market Index")).toBeInTheDocument();
    expect(screen.queryByText("Reference only")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Shown for context; not used in Market Index."),
    ).not.toBeInTheDocument();
  });

  it("stays silent for a below-minimum anomaly, whose own copy says it", () => {
    render(
      <Panel
        eligible={false}
        constraint="below_platform_minimum"
        contributes_to_index={false}
      />,
    );

    expect(screen.getByText("Source data anomaly")).toBeInTheDocument();
    expect(screen.queryByText("Reference only")).not.toBeInTheDocument();
  });

  // A sale price is a real, buyable price and counts toward the index. Its
  // chip must survive untouched, and nothing may imply it was excluded.
  it("leaves a contributing sale price with its own note and nothing else", () => {
    render(<Panel eligible constraint="sale_price" contributes_to_index={true} />);

    expect(screen.getByText("Sale price")).toBeInTheDocument();
    expect(screen.queryByText("Reference only")).not.toBeInTheDocument();
    expect(screen.queryByText("Not used in Market Index")).not.toBeInTheDocument();
  });

  // Both can legitimately appear: the constraint explains the number, the
  // contribution note explains the index. Neither restates the other.
  it("adds the contribution note beside a constraint that excludes nothing", () => {
    render(<Panel eligible constraint="sale_price" contributes_to_index={false} />);

    expect(screen.getByText("Sale price")).toBeInTheDocument();
    expect(screen.getByText("Reference only")).toBeInTheDocument();
    expect(screen.queryByText("Not used in Market Index")).not.toBeInTheDocument();
  });

  it("carries no warning vocabulary", () => {
    const { container } = render(<Panel eligible contributes_to_index={false} />);
    expect(container.textContent).not.toMatch(/warning|excluded|ignored|disagree/i);
  });
});
