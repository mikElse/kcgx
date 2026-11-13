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
      blue: read("--blue"), green: read("--green"), frame: read("--frame"),
    };
  }
  return cache;
}

// The settings the helpers below read. main.js calls bindTheme(store) once.
let prefs = null;
export function bindTheme(store) {
  prefs = () => store.state.prefs;
}

function setting(key) {
  if (!prefs) throw new Error("theme.js: bindTheme(store) has not been called");
  return prefs()[key];
}

// A glow's blur in CSS px. By layer (phase G decision 15), "map", "traffic"
// or "text": 0 to 100 is 0 to 12 px. With no layer, phase F's three steps
// from the data-glow bridge main.js keeps (OFF 0, LOW 4, FULL 9), which is
// what the radar and the traces draw with until their lanes move them to
// the layers; 33, the default, is 3.96 px and not quite LOW's 4.
const GLOW_LAYERS = new Set(["map", "traffic", "text"]);
export function glowBlur(layer) {
  if (layer === undefined) {
    const glow = document.documentElement.dataset.glow;
    return glow === "FULL" ? 9 : glow === "LOW" ? 4 : 0;
  }
  if (!GLOW_LAYERS.has(layer)) throw new Error(`theme.js: no glow layer ${layer}`);
  return (setting(`glow_${layer}`) * 12) / 100;
}

// How many backing-store pixels a canvas gives each device pixel, by the
// anti-aliasing setting (phase G decision 6): OFF half, ON the display's
// own, SUPER twice. Nothing applies it yet; each lane does for its canvases.
const RENDER_SCALE = { OFF: 0.5, ON: 1, SUPER: 2 };
export function renderScale() {
  return RENDER_SCALE[setting("aa")] ?? 1;
}

// Called when prefs change: the next read picks up the new palette.
export function forget() { cache = null; }

export function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
