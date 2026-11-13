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
// (OFF 0, LOW 4, FULL 9) from the map's number, which is what the radar
// draws with until its lanes move it to the layers; 33, the default, is
// 3.96 px and not quite LOW's 4.
const GLOW_LAYERS = new Set(["map", "traffic", "text"]);
export function glowBlur(layer) {
  if (layer === undefined) {
    const level = setting("glow_map");
    return level === 0 ? 0 : level <= 50 ? 4 : 9;
  }
  if (!GLOW_LAYERS.has(layer)) throw new Error(`theme.js: no glow layer ${layer}`);
  return (setting(`glow_${layer}`) * 12) / 100;
}

// The page's own glow, from the text layer's number (glow_text, 0 to 100),
// as the custom properties the stylesheet reads. The text's shadow is a
// wide halo and, above 33, a tight core under it, so the two phase F steps
// are exact: 33 is LOW (one 7 px halo) and 75 is FULL (a 4 px core and a
// 16 px halo). Below 33 the halo grows from nothing to LOW's; from 33 to
// 75 it grows to FULL's as the core fades in; above 75 both grow on in
// proportion. The screens' frames and the lit lamps glow while the text does.
export function textGlow() {
  const level = setting("glow_text");
  if (level === 0) return { glow: "none", frame: "none", lamp: "0px" };
  const between = (from, to) => from + ((to - from) * (level - 33)) / (75 - 33);
  const [core, halo] = level <= 33 ? [0, (7 * level) / 33]
    : level <= 75 ? [between(0, 4), between(7, 16)]
      : [(4 * level) / 75, (16 * level) / 75];
  const shadow = (blur) => `0 0 ${Math.round(blur * 100) / 100}px currentColor`;
  return {
    glow: core > 0 ? `${shadow(core)}, ${shadow(halo)}` : shadow(halo),
    frame: "0 0 14px color-mix(in srgb, var(--frame) 27%, transparent)",
    lamp: "10px",
  };
}

// The fonts (phase G decision 17), vendored in static/fonts: FONT's choice
// as the text's family and the display's (titles, big figures, the radar).
// CLASSIC is phase F's pair; each of the others is both. A face whose file
// is missing falls to the next family in its stack, the system's.
const SYSTEM = "ui-monospace, Menlo, monospace";
const FAMILY = {
  B612: '"B612 Mono"', SHARETECH: '"Share Tech Mono"', PLEX: '"IBM Plex Mono"',
  JETBRAINS: '"JetBrains Mono"', VT323: '"VT323"',
};
export function fontFamilies(choice) {
  if (choice === "SYSTEM") return { text: SYSTEM, display: SYSTEM };
  if (choice in FAMILY) {
    const stack = `${FAMILY[choice]}, ${SYSTEM}`;
    return { text: stack, display: stack };
  }
  return { text: `${FAMILY.B612}, ${SYSTEM}`, display: `${FAMILY.SHARETECH}, ${SYSTEM}` }; // CLASSIC
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
