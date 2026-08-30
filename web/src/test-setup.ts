import "@testing-library/jest-dom";

// jsdom has no layout engine: it reports every element's offsetWidth/offsetHeight
// as 0. @tanstack/react-virtual measures its scroll element and its rows through
// those properties (getRect + measureElement both read offsetHeight), so without
// a shim the virtualizer would size the viewport to 0 and render zero rows —
// breaking every test that asserts CacheTable rows are on screen.
//
// This gives the scroll container (tagged data-virtual-scroll) a deterministic
// viewport, and every other element a small non-zero size, so a representative
// window of rows mounts under jsdom while real browsers keep measuring for real.
const VIRTUAL_SCROLL_HEIGHT = 640;
const VIRTUAL_SCROLL_WIDTH = 900;
const DEFAULT_ELEMENT_HEIGHT = 40;
const DEFAULT_ELEMENT_WIDTH = 120;

function styleLength(el: HTMLElement, prop: "height" | "width"): number | null {
  const raw = el.style?.[prop];
  if (!raw) return null;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : null;
}

Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  get(this: HTMLElement) {
    if (this.hasAttribute("data-virtual-scroll")) return VIRTUAL_SCROLL_HEIGHT;
    return styleLength(this, "height") ?? DEFAULT_ELEMENT_HEIGHT;
  },
});

Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  get(this: HTMLElement) {
    if (this.hasAttribute("data-virtual-scroll")) return VIRTUAL_SCROLL_WIDTH;
    return styleLength(this, "width") ?? DEFAULT_ELEMENT_WIDTH;
  },
});
