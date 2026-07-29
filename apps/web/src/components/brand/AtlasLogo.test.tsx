import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AtlasCompactMark, AtlasLogo } from "./AtlasLogo";

describe("AtlasLogo", () => {
  it("renders the full product name and endorsement line", () => {
    render(<AtlasLogo />);
    expect(screen.getByText("CardPirate Atlas")).toBeInTheDocument();
    expect(screen.getByText("by CardPirateTCG")).toBeInTheDocument();
  });

  it("renders no forbidden franchise/old-brand terminology", () => {
    render(<AtlasLogo />);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/optcg vault|tcg vault|price tracker/i);
  });
});

describe("AtlasCompactMark", () => {
  it("always carries the full product name for assistive tech", () => {
    render(<AtlasCompactMark />);
    // sr-only span - present in the DOM even though visually hidden.
    expect(screen.getByText("CardPirate Atlas")).toBeInTheDocument();
  });

  it("shows the short wordmark by default", () => {
    render(<AtlasCompactMark />);
    expect(screen.getByText("Atlas")).toBeInTheDocument();
  });

  it("can hide the short wordmark for icon-only contexts", () => {
    render(<AtlasCompactMark showShortName={false} />);
    expect(screen.queryByText("Atlas")).not.toBeInTheDocument();
    expect(screen.getByText("CardPirate Atlas")).toBeInTheDocument();
  });

  it("suppresses its own sr-only name when aria-hidden (ancestor supplies the accessible name)", () => {
    render(<AtlasCompactMark aria-hidden />);
    expect(screen.queryByText("CardPirate Atlas")).not.toBeInTheDocument();
  });
});
