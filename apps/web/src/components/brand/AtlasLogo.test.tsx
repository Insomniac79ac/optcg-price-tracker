import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AtlasCompactMark, AtlasLogo } from "./AtlasLogo";

describe("AtlasLogo", () => {
  it("renders the full product name and endorsement line", () => {
    render(<AtlasLogo />);
    expect(screen.getByText("Card Pirate")).toBeInTheDocument();
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
    expect(document.querySelector(".sr-only")).toHaveTextContent("Card Pirate");
  });

  it("shows the short wordmark by default", () => {
    render(<AtlasCompactMark />);
    expect(screen.getAllByText("Card Pirate").find((node) => node.getAttribute("aria-hidden") === "true")).toBeInTheDocument();
  });

  it("can hide the short wordmark for icon-only contexts", () => {
    render(<AtlasCompactMark showShortName={false} />);
    expect(document.querySelector("span[aria-hidden] .font-display")).not.toBeInTheDocument();
    expect(screen.getByText("Card Pirate")).toBeInTheDocument();
  });

  it("suppresses its own sr-only name when aria-hidden (ancestor supplies the accessible name)", () => {
    render(<AtlasCompactMark aria-hidden />);
    expect(document.querySelector(".sr-only")).not.toBeInTheDocument();
  });
});
