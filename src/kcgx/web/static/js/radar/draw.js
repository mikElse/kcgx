// What the still and the moving layers both draw with: the font, and label
// boxes (prefs.box_items).
//
// Both layers are light added to light, so black over them changes
// nothing. A label's box is therefore painted on its own, replacing what is
// under it: a still label's on the static layer before its text, a flight
// tag's on the screen between the two layers.

// The display font, --font-display (prefs.font). main.js sets it with the
// prefs, which mark the static layer to be drawn again.
export let FONT = '"Share Tech Mono", monospace';
export function setFont(family) { FONT = family; }
export const CAP = 0.7; // the font's capitals and digits stand this much of its size above the baseline
const SPACED = "letterSpacing" in CanvasRenderingContext2D.prototype;

// -- label boxes -----------------------------------------------------------------

// measureText counts the letter spacing after the last letter too, where
// the canvas spaces letters at all.
export const trailing = (spacing) => (SPACED ? spacing : 0);

// What `lines` lines of capitals ink: `w` wide, `px` text, the first on
// `baseline` and each `step` under the last.
export function inked(x, baseline, w, px, lines = 1, step = 0) {
  return { x, y: baseline - CAP * px, w, h: CAP * px + (lines - 1) * step };
}

// The least rectangle that holds both.
export function around(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
}

// Whether two rectangles meet; touching is meeting.
export function meets(a, b) {
  return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
}

function borderWidth(ratio, prefs) {
  return Math.max(1, Math.round(prefs.box_width * ratio));
}

// A label's box: what it inks, the padding about that and the border about
// the padding, as CSS lays out the readouts' boxes. On whole pixels, so
// that a thin border is a sharp one.
export function boxAbout(ink, ratio, prefs) {
  const margin = prefs.box_pad * ratio + borderWidth(ratio, prefs);
  const x = Math.round(ink.x - margin);
  const y = Math.round(ink.y - margin);
  return { x, y, w: Math.round(ink.x + ink.w + margin) - x, h: Math.round(ink.y + ink.h + margin) - y };
}

// What a label keeps to itself, for placing, hovering and clicking: its
// text's rectangle as ever and, when it is boxed, its box as well. The text
// is where it would be without a box.
export function claim(text, ink, boxed, ratio, prefs) {
  const box = boxed ? boxAbout(ink, ratio, prefs) : null;
  return { ...(box ? around(text, box) : text), boxed, box };
}

// The one place a box is painted: black at the fill's strength, edged
// inside in the label's colour at the border's. Always over what is there,
// whatever the canvas was doing.
export function paintBox(ctx, r, colour, ratio, prefs, alpha = 1) {
  const lw = borderWidth(ratio, prefs);
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.shadowBlur = 0;
  ctx.setLineDash([]);
  ctx.lineJoin = "miter";
  ctx.globalAlpha = alpha * (prefs.box_fill / 100);
  ctx.fillStyle = "#000";
  ctx.fillRect(r.x, r.y, r.w, r.h);
  if (prefs.box_border > 0) {
    ctx.globalAlpha = alpha * (prefs.box_border / 100);
    ctx.strokeStyle = colour;
    ctx.lineWidth = lw;
    ctx.strokeRect(r.x + lw / 2, r.y + lw / 2, r.w - lw, r.h - lw);
  }
  ctx.restore();
}
