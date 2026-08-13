import { describe, expect, it } from "vitest";

import {
  isValidGeometry,
  matchesNaturalSize,
  placeCardBox,
  type CardBoxGeometry,
} from "./cardGeometry";

const FRAME_ASPECT = 63 / 88;

/** The real staging shape: a landscape canvas with the card centred in
 * transparent padding. Used as *data*, never as a constant in the module. */
function snkrdunkGeometry(overrides: Partial<CardBoxGeometry> = {}): CardBoxGeometry {
  return {
    canvas_px: { width: 856, height: 625 },
    card_bbox_px: { x: 241, y: 51, width: 374, height: 523 },
    ...overrides,
  };
}

/** Resolve a placement back into the card's on-screen box, the way a browser
 * would, so assertions are about what the user sees. */
function renderedCard(geometry: CardBoxGeometry, frameW: number) {
  const frameH = frameW / FRAME_ASPECT;
  const p = placeCardBox(geometry, FRAME_ASPECT);
  const imgW = (p.widthPct / 100) * frameW;
  const scale = imgW / geometry.canvas_px.width;
  const imgLeft = (p.leftPct / 100) * frameW;
  const imgTop = (p.topPct / 100) * frameH;
  const box = geometry.card_bbox_px;
  return {
    frameW,
    frameH,
    left: imgLeft + box.x * scale,
    top: imgTop + box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
  };
}

describe("isValidGeometry", () => {
  it("accepts the verified staging geometry", () => {
    expect(isValidGeometry(snkrdunkGeometry())).toBe(true);
  });

  it("rejects missing geometry", () => {
    expect(isValidGeometry(null)).toBe(false);
    expect(isValidGeometry(undefined)).toBe(false);
  });

  it.each([
    ["zero canvas width", { canvas_px: { width: 0, height: 625 } }],
    ["zero canvas height", { canvas_px: { width: 856, height: 0 } }],
    ["negative canvas", { canvas_px: { width: -856, height: 625 } }],
    ["zero box width", { card_bbox_px: { x: 241, y: 51, width: 0, height: 523 } }],
    ["zero box height", { card_bbox_px: { x: 241, y: 51, width: 374, height: 0 } }],
    ["negative origin x", { card_bbox_px: { x: -1, y: 51, width: 374, height: 523 } }],
    ["negative origin y", { card_bbox_px: { x: 241, y: -1, width: 374, height: 523 } }],
    ["box overflows right", { card_bbox_px: { x: 700, y: 51, width: 374, height: 523 } }],
    ["box overflows bottom", { card_bbox_px: { x: 241, y: 400, width: 374, height: 523 } }],
  ])("rejects malformed geometry: %s", (_label, overrides) => {
    expect(isValidGeometry(snkrdunkGeometry(overrides as Partial<CardBoxGeometry>))).toBe(false);
  });
});

describe("matchesNaturalSize - the mandatory safety guard", () => {
  const geometry = snkrdunkGeometry();

  it("matches the exact asset the geometry was measured against", () => {
    expect(matchesNaturalSize(geometry, 856, 625)).toBe(true);
  });

  it("rejects a natural width mismatch", () => {
    expect(matchesNaturalSize(geometry, 857, 625)).toBe(false);
    expect(matchesNaturalSize(geometry, 428, 625)).toBe(false);
  });

  it("rejects a natural height mismatch", () => {
    expect(matchesNaturalSize(geometry, 856, 626)).toBe(false);
    expect(matchesNaturalSize(geometry, 856, 312)).toBe(false);
  });

  it("rejects an unloaded image reporting 0x0", () => {
    expect(matchesNaturalSize(geometry, 0, 0)).toBe(false);
  });
});

describe("placeCardBox", () => {
  it("fills the frame with the card instead of the canvas", () => {
    const card = renderedCard(snkrdunkGeometry(), 222);

    // Was ~43% of frame width before this fix.
    expect(card.width / card.frameW).toBeGreaterThan(0.99);
    expect(card.height / card.frameH).toBeGreaterThan(0.99);
  });

  it("never lets the card exceed the frame on either axis", () => {
    const card = renderedCard(snkrdunkGeometry(), 222);

    expect(card.width).toBeLessThanOrEqual(card.frameW + 1e-6);
    expect(card.height).toBeLessThanOrEqual(card.frameH + 1e-6);
  });

  it("keeps every card pixel inside the frame - nothing is clipped", () => {
    for (const frameW of [163.5, 191, 232.7, 222, 400]) {
      const card = renderedCard(snkrdunkGeometry(), frameW);
      expect(card.left).toBeGreaterThanOrEqual(-1e-6);
      expect(card.top).toBeGreaterThanOrEqual(-1e-6);
      expect(card.left + card.width).toBeLessThanOrEqual(card.frameW + 1e-6);
      expect(card.top + card.height).toBeLessThanOrEqual(card.frameH + 1e-6);
    }
  });

  it("preserves the card's aspect ratio exactly", () => {
    const geometry = snkrdunkGeometry();
    const card = renderedCard(geometry, 222);
    const sourceAspect = geometry.card_bbox_px.width / geometry.card_bbox_px.height;

    expect(card.width / card.height).toBeCloseTo(sourceAspect, 6);
  });

  it("centres the card in the frame", () => {
    const card = renderedCard(snkrdunkGeometry(), 222);

    expect(card.left).toBeCloseTo(card.frameW - (card.left + card.width), 6);
    expect(card.top).toBeCloseTo(card.frameH - (card.top + card.height), 6);
  });

  it("scales proportionally with the frame, so behaviour is width-independent", () => {
    const small = renderedCard(snkrdunkGeometry(), 163.5);
    const large = renderedCard(snkrdunkGeometry(), 400);

    expect(small.width / small.frameW).toBeCloseTo(large.width / large.frameW, 6);
  });

  it("is driven by data, not by any hardcoded canvas - a different asset shape works too", () => {
    // A hypothetical host that pads a portrait canvas instead.
    const other: CardBoxGeometry = {
      canvas_px: { width: 500, height: 900 },
      card_bbox_px: { x: 40, y: 120, width: 420, height: 587 },
    };
    const card = renderedCard(other, 300);

    expect(card.width / card.frameW).toBeGreaterThan(0.98);
    expect(card.left).toBeGreaterThanOrEqual(-1e-6);
    expect(card.top).toBeGreaterThanOrEqual(-1e-6);
    expect(card.width / card.height).toBeCloseTo(420 / 587, 6);
  });

  it("handles a card already flush with the canvas edge, with no padding to give back", () => {
    const flush: CardBoxGeometry = {
      canvas_px: { width: 374, height: 523 },
      card_bbox_px: { x: 0, y: 0, width: 374, height: 523 },
    };
    const card = renderedCard(flush, 222);

    expect(card.left).toBeGreaterThanOrEqual(-1e-6);
    expect(card.top).toBeGreaterThanOrEqual(-1e-6);
    expect(card.width).toBeLessThanOrEqual(card.frameW + 1e-6);
    expect(card.height).toBeLessThanOrEqual(card.frameH + 1e-6);
  });

  it("fits by the tighter axis - a wide card box is limited by width, not height", () => {
    const wide: CardBoxGeometry = {
      canvas_px: { width: 1000, height: 1000 },
      card_bbox_px: { x: 100, y: 400, width: 800, height: 200 },
    };
    const card = renderedCard(wide, 222);

    expect(card.width).toBeLessThanOrEqual(card.frameW + 1e-6);
    expect(card.height).toBeLessThan(card.frameH);
    expect(card.width / card.frameW).toBeGreaterThan(0.98);
  });
});
