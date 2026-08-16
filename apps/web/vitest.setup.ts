import "@testing-library/jest-dom/vitest";

// jsdom implements no CSSOM view module, so `window.matchMedia` simply does
// not exist there. Any component that adapts to a breakpoint in JS (rather
// than in CSS) needs it - CatalogueIntro shortens its search placeholder on
// narrow viewports this way. The shim reports "does not match", which is the
// desktop branch and the same value the components use for their server
// snapshot, so tests render the wide layout unless they override this.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
