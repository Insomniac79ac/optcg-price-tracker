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

/** The shape the mirrored R2 display images actually have on staging: a tight
 * crop, so the verified card box *is* the whole canvas. These are the prints
 * that used to render edge-to-edge while every other tile in the same grid sat
 * inset, because `padded` reached only the contain path. */
const FULL_CANVAS_GEOMETRY: CardBoxGeometry = {
  canvas_px: { width: 600, height: 838 },
  card_bbox_px: { x: 0, y: 0, width: 600, height: 838 },
};

describe("CardImageFrame framing consistency", () => {
  it("takes the contain path for a tight crop, so `padded` still applies", () => {
    const { container } = render(
      <CardImageFrame
        imageUrl={SNKRDUNK}
        alt="Sanji (OP01-013)"
        cardCode="OP01-013"
        geometry={FULL_CANVAS_GEOMETRY}
        padded
      />,
    );
    const img = loadAndSettle([600, 838]);

    // Bounded placement has nothing to correct here, so it must not engage:
    // engaging it is exactly what dropped the inset on these prints.
    expect(img.className).toContain("object-contain");
    expect(img.className).toContain("p-1.5");
    expect(img.style.width).toBe("");
    expect(container.querySelector(".vault-frame")!.className).toContain("overflow-hidden");
  });

  it("frames a tight-crop print and a plain print identically", () => {
    // Equivalent inputs - same tile, same `padded` - must reach the same
    // classes, which is the same rendered gutter.
    const withGeometry = render(
      <CardImageFrame
        imageUrl={SNKRDUNK}
        alt="Sanji (OP01-013)"
        cardCode="OP01-013"
        geometry={FULL_CANVAS_GEOMETRY}
        size="full"
        padded
      />,
    );
    const geometryClasses = loadAndSettle([600, 838]).className;
    withGeometry.unmount();

    const plain = render(
      <CardImageFrame
        imageUrl={BANDAI}
        alt="Sanji (OP01-013)"
        cardCode="OP01-013"
        size="full"
        padded
      />,
    );
    const plainClasses = (plain.container.querySelector("img") as HTMLImageElement).className;

    expect(geometryClasses).toBe(plainClasses);
  });

  it("still corrects an asset that really is composited onto a bigger canvas", () => {
    // The guard must not disarm bounded placement where it earns its keep -
    // GEOMETRY's card box is a strict sub-rectangle of its canvas.
    render(boundedUi);
    const img = loadAndSettle([856, 625]);

    expect(parseFloat(img.style.width)).toBeGreaterThan(200);
    expect(img.className).not.toContain("object-contain");
  });

  it("keeps the whole card visible, never cropped or filled", () => {
    const tight = render(
      <CardImageFrame
        imageUrl={SNKRDUNK}
        alt="Sanji (OP01-013)"
        cardCode="OP01-013"
        geometry={FULL_CANVAS_GEOMETRY}
        padded
      />,
    );
    const tightImg = loadAndSettle([600, 838]);
    expect(tightImg.className).toContain("object-contain");
    expect(tightImg.className).not.toContain("object-cover");
    expect(tightImg.className).not.toContain("object-fill");
    tight.unmount();

    const plain = render(
      <CardImageFrame imageUrl={BANDAI} alt="Sanji (OP01-013)" cardCode="OP01-013" padded />,
    );
    const plainImg = plain.container.querySelector("img") as HTMLImageElement;
    expect(plainImg.className).toContain("object-contain");
    expect(plainImg.className).not.toContain("object-cover");
    expect(plainImg.className).not.toContain("object-fill");
  });

  it("renders the supplied URL verbatim - no client-side source rewriting", () => {
    const tight = render(
      <CardImageFrame
        imageUrl={SNKRDUNK}
        alt="Sanji (OP01-013)"
        cardCode="OP01-013"
        geometry={FULL_CANVAS_GEOMETRY}
        padded
      />,
    );
    expect(loadAndSettle([600, 838]).getAttribute("src")).toBe(SNKRDUNK);
    tight.unmount();

    const plain = render(
      <CardImageFrame imageUrl={BANDAI} alt="Sanji (OP01-013)" cardCode="OP01-013" padded />,
    );
    expect((plain.container.querySelector("img") as HTMLImageElement).getAttribute("src")).toBe(
      BANDAI,
    );
  });
});

describe("collector surfaces share this component", () => {
  const consumers = [
    // /cards - the public catalogue grid tile.
    "src/components/ui/PrintCardTile.tsx",
    // Analytics - the "Cards in this view" strip.
    "src/components/ui/MarketLandscapeCards.tsx",
  ];

  it.each(consumers)("%s renders CardImageFrame rather than its own <img>", async (path) => {
    const fs = await import("fs/promises");
    const source = await fs.readFile(path, "utf8");

    expect(source).toMatch(/from "(\.\/|@\/components\/ui\/)CardImageFrame"/);
    expect(source).toContain("<CardImageFrame");
    // No consumer may hand-roll artwork: the framing contract is the shared
    // component's to keep, which is the whole point of this tranche.
    expect(source).not.toMatch(/<img\b/);
  });

  it.each(consumers)("%s asks for the same padded framing", async (path) => {
    const fs = await import("fs/promises");
    const source = await fs.readFile(path, "utf8");
    const frameProps = source.slice(
      source.indexOf("<CardImageFrame"),
      source.indexOf("/>", source.indexOf("<CardImageFrame")),
    );

    // Identical framing inputs on both surfaces, so /cards and Analytics
    // cannot drift back into two different card-image presentations.
    expect(frameProps).toContain("padded");
    expect(frameProps).toContain('size="full"');
    expect(frameProps).toContain("geometry={print.imageGeometry}");
  });
});
