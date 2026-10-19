// Palette colours for the canvases, read from the CSS custom properties the
// stylesheet sets per palette, so the DOM and the canvases always agree.

let cache = null;

export function colours() {
  if (!cache) {
    const css = getComputedStyle(document.documentElement);
    const read = (name) => css.getPropertyValue(name).trim();
    cache = {
      cyan: read("--cyan"), dim: read("--dim"), pink: read("--pink"), white: read("--white"),
      amber: read("--amber"), alarm: read("--alarm"), muted: read("--muted"), text: read("--text"),
    };
  }
  return cache;
}

export function glowBlur() {
  const glow = document.documentElement.dataset.glow;
  return glow === "FULL" ? 9 : glow === "LOW" ? 4 : 0;
}

// Called when prefs change: the next read picks up the new palette.
export function forget() { cache = null; }

export function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
