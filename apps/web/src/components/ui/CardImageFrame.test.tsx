import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardImageFrame } from "./CardImageFrame";
import type { CardBoxGeometry } from "@/lib/cardGeometry";

const SNKRDUNK = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l";
const BANDAI = "/api/card-image?u=https%3A%2F%2Fwww.onepiece-cardgame.com%2FOP01-013.png";

const GEOMETRY: CardBoxGeometry = {
  canvas_px: { width: 856, height: 625 },
  card_bbox_px: { x: 241, y: 51, width: 374, height: 523 },
};

/** jsdom never loads images, so intrinsic size has to be installed by hand -
 * this is what the component's safety guard actually reads. */
function loadImageAs(img: HTMLImageElement, width: number, height: number) {
  Object.defineProperty(img, "naturalWidth", { value: width, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: height, configurable: true });
  Object.defineProperty(img, "complete", { value: true, configurable: true });
}

function renderFrame(props: Partial<Parameters<typeof CardImageFrame>[0]> = {}) {
  return render(
    <CardImageFrame imageUrl={SNKRDUNK} alt="Sanji (OP01-013)" cardCode="OP01-013" {...props} />,
  );
}

/** Give the image an intrinsic size and fire the real load event, which is
 * what drives the component's guard. Returns the image as it renders after. */
function loadAndSettle(size: [number, number]) {
  const img = screen.getByRole("img") as HTMLImageElement;
  loadImageAs(img, size[0], size[1]);
  fireEvent.load(img);
  return screen.getByRole("img") as HTMLImageElement;
}

const boundedUi = (
  <CardImageFrame
    imageUrl={SNKRDUNK}
    alt="Sanji (OP01-013)"
    cardCode="OP01-013"
    geometry={GEOMETRY}
  />
);

describe("CardImageFrame bounded presentation", () => {
  it("applies bounded placement once the image loads at the recorded canvas size", () => {
    render(boundedUi);
    const img = loadAndSettle([856, 625]);

    // Scaled well past the frame so the card - not the canvas - fills it.
    expect(parseFloat(img.style.width)).toBeGreaterThan(200);
    expect(parseFloat(img.style.left)).toBeLessThan(0);
    expect(parseFloat(img.style.top)).toBeLessThan(0);
    expect(img.className).not.toContain("object-contain");
  });

  it("never uses object-fit: cover", () => {
    render(boundedUi);
    const img = loadAndSettle([856, 625]);

    expect(img.className).not.toContain("object-cover");
    expect(img.style.objectFit).not.toBe("cover");
  });

  it("clips squarely in bounded mode so the frame radius cannot shave card corners", () => {
    const { container } = render(boundedUi);
    loadAndSettle([856, 625]);

    const frame = container.querySelector(".vault-frame")!;
    expect(frame.className).not.toContain("overflow-hidden");
    expect(container.querySelector(".absolute.inset-0.overflow-hidden")).not.toBeNull();
  });
});

describe("CardImageFrame fallback paths", () => {
  it("renders a Bandai image with plain object-contain", () => {
    renderFrame({ imageUrl: BANDAI, geometry: null });
    const img = screen.getByRole("img");

    expect(img.className).toContain("object-contain");
    expect(img.getAttribute("style")).toBeNull();
  });

  it("falls back when no geometry is supplied at all", () => {
    const ui = <CardImageFrame imageUrl={SNKRDUNK} alt="a" cardCode="OP01-013" />;
    render(ui);
    const img = loadAndSettle([856, 625]);

    expect(img.className).toContain("object-contain");
  });

  it("falls back on a naturalWidth mismatch", () => {
    render(boundedUi);
    const img = loadAndSettle([428, 625]);

    expect(img.className).toContain("object-contain");
    expect(img.getAttribute("style")).toBeNull();
  });

  it("falls back on a naturalHeight mismatch", () => {
    render(boundedUi);
    const img = loadAndSettle([856, 312]);

    expect(img.className).toContain("object-contain");
  });

  it("stays in the fallback path before the image has loaded", () => {
    render(boundedUi);

    expect(screen.getByRole("img").className).toContain("object-contain");
  });

  it.each([
    ["bbox wider than the canvas", { x: 700, y: 51, width: 374, height: 523 }],
    ["bbox taller than the canvas", { x: 241, y: 400, width: 374, height: 523 }],
    ["negative origin", { x: -1, y: 51, width: 374, height: 523 }],
    ["zero-sized bbox", { x: 241, y: 51, width: 0, height: 523 }],
  ])("falls back on malformed geometry: %s", (_label, card_bbox_px) => {
    const ui = (
      <CardImageFrame
        imageUrl={SNKRDUNK}
        alt="a"
        cardCode="OP01-013"
        geometry={{ ...GEOMETRY, card_bbox_px }}
      />
    );
    render(ui);
    const img = loadAndSettle([856, 625]);

    expect(img.className).toContain("object-contain");
  });

  it("still shows the placeholder when the image fails to load", () => {
    renderFrame({ imageUrl: null, rarity: "R", setCode: "OP-01" });

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("OP01-013")).toBeTruthy();
  });
});
