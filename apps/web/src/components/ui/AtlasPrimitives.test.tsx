import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AtlasArtworkStage,
  AtlasDivider,
  AtlasMapSurface,
  AtlasReleaseDestination,
  AtlasSectionIntro,
  AtlasVisualSystem,
} from "./AtlasPrimitives";

describe("Atlas presentation contracts", () => {
  it("names a section by its heading without announcing the decorative number", () => {
    render(<section aria-labelledby="moves"><AtlasSectionIntro id="moves" number="01" title="Cards on the move" /></section>);
    expect(screen.getByRole("heading", { level: 2, name: "Cards on the move" })).toHaveAttribute("id", "moves");
    expect(screen.getByRole("region", { name: "Cards on the move" })).toBeInTheDocument();
    expect(screen.getByText("01")).toHaveAttribute("aria-hidden", "true");
  });

  it("supports nested headings and hides every piece of map geometry", () => {
    const { container } = render(<AtlasVisualSystem><AtlasMapSurface><AtlasSectionIntro id="release" title="Explore releases" level={3} /></AtlasMapSurface><AtlasDivider /></AtlasVisualSystem>);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Explore releases");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    for (const svg of container.querySelectorAll("svg")) {
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("focusable", "false");
    }
  });

  it("uses the official release name without changing the code or destination", () => {
    render(<AtlasReleaseDestination releaseCode="PRB-01" href="/cards?set=PRB-01" />);
    expect(screen.getByRole("link", { name: "PRB-01 ONE PIECE CARD THE BEST" })).toHaveAttribute("href", "/cards?set=PRB-01");
  });

  it.each([
    ["OP-01", "Romance Dawn"],
    ["OP-02", "Paramount War"],
    ["OP-03", "Pillars of Strength"],
    ["OP-04", "Kingdoms of Intrigue"],
    ["PRB-02", "ONE PIECE CARD THE BEST vol.2"],
  ])("shows the official title for %s", (code, name) => {
    render(<AtlasReleaseDestination releaseCode={code} href={`/cards?set=${code}`} />);
    expect(screen.getByRole("link", { name: `${code} ${name}` })).toHaveAttribute("href", `/cards?set=${code}`);
  });

  it("uses concise neutral fallbacks for unknown and uncoded products", () => {
    const { rerender } = render(<AtlasReleaseDestination releaseCode="FUTURE-99" href="/cards?release_product_id=999" />);
    expect(screen.getByRole("link", { name: "FUTURE-99" })).toHaveAttribute("href", "/cards?release_product_id=999");
    rerender(<AtlasReleaseDestination releaseCode={null} href="/cards?release_product_id=1000" />);
    expect(screen.getByRole("link", { name: "Special product" })).toHaveAttribute("href", "/cards?release_product_id=1000");
  });

  it("keeps captions outside the image frame and resets a failed image for a different printing", () => {
    const image = { imageUrl: "/base.png", alt: "Nami (OP01-016)", cardCode: "OP01-016" };
    const { container, rerender } = render(<AtlasArtworkStage image={image} caption="Found in OP-01" />);
    expect(screen.getByRole("img").className).toContain("object-contain");
    expect(screen.getByRole("img").className).toContain("p-1.5");
    expect(container.querySelector(".vault-frame")!.contains(screen.getByText("Found in OP-01"))).toBe(false);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    rerender(<AtlasArtworkStage image={{ ...image, imageUrl: "/parallel.png" }} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/parallel.png");
  });

  it("passes verified padded-canvas geometry through the frame's natural-size guard", () => {
    const image = {
      imageUrl: "/verified.webp", alt: "Sanji (OP01-013)", cardCode: "OP01-013",
      geometry: { canvas_px: { width: 856, height: 625 }, card_bbox_px: { x: 241, y: 51, width: 374, height: 523 } },
    };
    render(<AtlasArtworkStage image={image} />);
    const img = screen.getByRole("img");
    Object.defineProperty(img, "naturalWidth", { value: 428, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: 625, configurable: true });
    fireEvent.load(img);
    expect(screen.getByRole("img").className).toContain("object-contain");
    Object.defineProperty(img, "naturalWidth", { value: 856 });
    fireEvent.load(img);
    expect(parseFloat(screen.getByRole("img").style.width)).toBeGreaterThan(200);
  });
});
