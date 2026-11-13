// The boot animation's scene (phase G Task 14): the owner's "Vector
// Cockpit" drawing, ported from `Vector Cockpit Drawing/vector-scene.jsx`
// (a React component in a design tool's runtime, kept out of the repo,
// plan decision 22) to a 2D canvas. Line numbers below are that file's.
//
// Everything is a function of one time: `frame(ctx, T, colours, options)`
// draws the scene at T, the original's authored seconds, and keeps nothing.
// `authored(t)` turns playback seconds (0 to LENGTH) into T, as the
// design tool's engine does (animations-v3.jsx, ccDerive and ccWarp).
//
// What the port leaves out, and why:
// - the four ghost renders that were its burn-in (vector-scene.jsx:123): the
//   canvas fades by the burn_in setting instead, as the radar's moving
//   layer does (boot.js);
// - its motion blur (vector-scene.jsx:106-114), feGaussianBlur filters
//   along the turn and the takeoff roll, which a canvas could only fake;
// - its scanlines and vignette (vector-scene.jsx:133-134): the cover holds
//   the page's own .ovl, which follows the display setting;
// - its frame rate of 24 (vector-scene.jsx:121, the .dc.html's default):
//   frames.js holds it to fps_max like every other canvas;
// - its two-blur glow filter (vector-scene.jsx:127): the glow is one blur
//   of the map layer's (glowBlur("map")), a shadow on each stroke here or a
//   blurred copy of the scene under it (boot.js);
// - its phosphor palettes (vector-scene.jsx:15-22): the page's palette
//   stands in (`paletteOf`, below).

// -- the clock: animations-v3.jsx --------------------------------------------

const clamp = (v, min, max) => Math.max(min, Math.min(max, v)); // animations-v3.jsx:230
const Easing = { // animations-v3.jsx:169-180, the three the scene uses
  linear: (t) => t,
  easeOutQuad: (t) => t * (2 - t),
  easeInOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
};

// The scene list (Vector Cockpit.dc.html:13): each scene's playback length
// and the authored length it plays (its `nat`, where the tool retimed it).
// Lights plays 5 authored seconds over 5.5, and Outro 5 over 4.
const SCENES = [
  ["Draw", 3, 3], ["Takeoff", 3, 3], ["Turn", 3.2, 3.2], ["Tower", 3, 3], ["Lights", 5.5, 5], ["Outro", 4, 5],
];
const CUES = {}; // scene -> authored start: Draw 0, Takeoff 3, Turn 6, Tower 9.2, Lights 12.2, Outro 17.2
const SECTIONS = [];
{
  let play = 0, auth = 0;
  for (const [name, dur, nat] of SCENES) {
    CUES[name] = Math.round(auth * 1000) / 1000;
    SECTIONS.push({ play, dur, auth, nat });
    play += dur;
    auth += nat;
  }
}
export const LENGTH = SECTIONS.reduce((sum, s) => sum + s.dur, 0); // 21.7 s of playback
const AUTHORED = SECTIONS.reduce((sum, s) => sum + s.nat, 0); // 22.2 s of scene

// Playback seconds to the scene's own (animations-v3.jsx:978-989, ccWarp).
export function authored(t) {
  const s = SECTIONS.find((one) => t < one.play + one.dur) || SECTIONS[SECTIONS.length - 1];
  const local = clamp(t - s.play, 0, s.dur);
  return Math.min(s.auth + local * (s.nat / s.dur), AUTHORED);
}

// -- the drawing: vector-scene.jsx -------------------------------------------

// The scene's elements (vector-scene.jsx:2), in its own coordinates (a
// 1440 by 810 view from x = -180). `b` is a skyline building, `rw` part of
// the runway strip, `run` a runway path redrawn as the roll moves it on
// (its `d` is runway(s)[run]); `dash`, `alpha` and `width` are its style.
const ELS = [
  { d: "M-1200 408 L2280 408" },
  { d: "M760 414 L1380 414", dash: [6, 8], alpha: 0.7 },
  { d: "M-180 408 L-180 393.6 L-172.8 393.6 L-172.8 384 L-156 384 A12 12 0 0 1 -132 384 L-115.2 384 L-115.2 388.8 L-108 388.8", b: 1 },
  { d: "M-108 388.8 L-108 388.8 L-103.2 388.8 L-103.2 379.2 L-100.8 379.2 L-99.6 338.4 L-102 338.4 L-102 333.6 L-97.2 328.8 L-94.8 322.8 L-92.4 328.8 L-87.6 333.6 L-87.6 338.4 L-90 338.4 L-88.8 379.2 L-86.4 379.2", b: 1 },
  { d: "M-86.4 379.2 L-86.4 398.4 L-79.2 398.4 L-79.2 364.8 L-79.2 321.6 L-65.4 297.6 L-65.4 280.8 L-64.2 280.8 L-64.2 297.6 L-50.4 321.6 L-50.4 364.8", b: 1 },
  { d: "M-50.4 364.8 L-50.4 381.6 L-43.2 381.6 L-43.2 360 L-43.2 297.6 L-39.6 297.6 L-39.6 288 L-36 282 L-32.4 288 L-32.4 297.6 L-18 297.6 L-18 288 L-14.4 282 L-10.8 288 L-10.8 297.6 L-7.2 297.6 L-7.2 364.8", b: 1 },
  { d: "M-7.2 364.8 L-7.2 400.8 L0 400.8 L0 367.2 L0 304.8 L4.8 300 L4.8 273.6 L10.8 273.6 L10.8 244.8 L15.6 244.8 L15.6 206.4 L19.2 206.4 L19.2 244.8 L24 244.8 L24 201.6 L27.6 201.6 L27.6 244.8 L32.4 244.8 L32.4 261.6 L36 266.4 L36 314.4 L40.8 314.4 L40.8 350.4 L44.4 355.2 L44.4 372", b: 1 },
  { d: "M44.4 372 L44.4 391.2 L50.4 391.2 L50.4 372 L50.4 338.4 L57.6 338.4 L57.6 362.4", b: 1 },
  { d: "M57.6 362.4 L57.6 396 L62.4 396 L62.4 362.4 L62.4 300 L67.2 295.2 Q76.8 280.8 93.6 284.4 L93.6 290.4 L98.4 295.2 L98.4 379.2", b: 1 },
  { d: "M98.4 379.2 L98.4 388.8 L108 388.8 L108 379.2 L108 321.6 L117.6 321.6 L117.6 278.4 L129.6 278.4 L129.6 268.8 L136.2 268.8 L136.2 232.8 L137.4 232.8 L137.4 268.8 L141.6 268.8 L141.6 283.2 L146.4 283.2 L146.4 328.8 L156 328.8 L156 376.8", b: 1 },
  { d: "M156 376.8 L156 398.4 L163.2 398.4 L163.2 379.2 L168 302.4 L172.8 302.4 L172.8 297.6 L177.6 297.6 L178.8 271.2 L180 297.6 L194.4 297.6 L195.6 271.2 L196.8 297.6 L201.6 297.6 L201.6 302.4 L206.4 302.4 L211.2 379.2", b: 1 },
  { d: "M211.2 379.2 L211.2 381.6 L216 381.6 L216 381.6 L216 278.4 L220.8 278.4 L220.8 273.6 L232.8 273.6 L232.8 261.6 L236.4 261.6 L236.4 273.6 L249.6 273.6 L249.6 276 L254.4 276 L254.4 364.8", b: 1 },
  { d: "M254.4 364.8 L254.4 400.8 L259.2 400.8 L259.2 364.8 L259.2 333.6 L261.6 333.6 L262.8 314.4 L264 333.6 L280.8 333.6 L282 314.4 L283.2 333.6 L288 333.6 L288 340.8 L290.4 340.8 L290.4 381.6", b: 1 },
  { d: "M290.4 381.6 L290.4 391.2 L295.2 391.2 L295.2 381.6 L295.2 345.6 L298.8 345.6 L298.8 340.8 L303.6 337.2 L308.4 340.8 L310.8 345.6 L314.4 345.6 L314.4 360 L319.2 360 L319.2 388.8", b: 1 },
  { d: "M319.2 388.8 L319.2 396 L324 396 L324 388.8 L324 372 L331.2 372 L331.2 367.2 L336 367.2 L336 374.4 L340.8 374.4 L340.8 391.2", b: 1 },
  { d: "M340.8 391.2 L340.8 388.8 L345.6 388.8 L345.6 393.6 L345.6 384 L355.2 384 L355.2 357.6 L360 357.6 L360 379.2 L369.6 379.2 L379.2 384 L384 384 L384 396 L384 408", b: 1 },
  { d: "M614 408 L614 400 L666 400 L666 408 M622 400 A18 16 0 0 1 658 400 M640 384 L640 380" },
  { d: "M690 406 L700 402 L740 402 L750 406" },
  { d: "M532 410 L-300 475.7", rw: 1 },
  { d: "M558 410 L1380 465.1", rw: 1 },
  { d: "M520 410 L-300 465.2", rw: 1, alpha: 0.5 },
  { d: "M545 410 L545 416 M545 421 L546 430 M546 436 L547 446", rw: 1 },
  { d: "M539 410 L60 810 M551 410 L1030 810", rw: 1 },
  { run: "center", rw: 1, width: 2 },
  { run: "thresh", rw: 1 },
  { run: "lights", rw: 1, width: 3.5 },
];

// The runway's moving parts after a roll of s (vector-scene.jsx:3-13): the
// centre line's dashes, the threshold bars and the edge lights, in
// perspective from a vanishing point at (545, 410).
function runway(s) {
  const vx = 545, f = (n) => Math.round(n * 10) / 10, Y = (D) => 410 + 400 / D, X = (D, u) => vx + (485 / D) * u;
  let c = "", t = "", l = "";
  const o = ((s % 3) + 3) % 3;
  for (let D = 1 - o; D < 80; D += 3) {
    const a = Math.max(D, 0.3), b = D + 1.4;
    if (b <= 0.3) continue;
    c += "M" + vx + " " + f(Y(a)) + " L" + vx + " " + f(Y(b)) + " ";
  }
  const A = 1.15 - s, B = 1.45 - s;
  if (B > 0.3) {
    const a = Math.max(A, 0.3);
    for (let i = -4; i <= 4; i++) {
      if (!i) continue;
      const u = i / 5, w = 0.06;
      t += "M" + f(X(a, u - w)) + " " + f(Y(a)) + " L" + f(X(a, u + w)) + " " + f(Y(a)) + " L" + f(X(B, u + w)) + " "
        + f(Y(B)) + " L" + f(X(B, u - w)) + " " + f(Y(B)) + " Z ";
    }
  }
  const lo = ((s % 2.5) + 2.5) % 2.5;
  for (let D = 1.2 - lo; D < 60; D += 2.5) {
    if (D <= 0.35) continue;
    const y = f(Y(D)), xl = f(X(D, -1.017)), xr = f(X(D, 1.017));
    l += "M" + xl + " " + y + " L" + f(xl + 0.5) + " " + y + " M" + xr + " " + y + " L" + f(xr + 0.5) + " " + y + " ";
  }
  return { center: c, thresh: t, lights: l };
}

const MOTION = { draw: Easing.easeOutQuad, line: Easing.linear, turn: Easing.easeInOutCubic }; // :14

// Each element's colour role (vector-scene.jsx:23-31).
function roleOf(el) {
  if (el.b) return "sky";
  if (el.run) return el.run === "center" ? "center" : el.run;
  const d = el.d || "";
  if (el.rw) return d.startsWith("M545") ? "center" : "edge";
  if (d.startsWith("M614") || d.startsWith("M690")) return "dome";
  return "horizon";
}
const ROLES = ELS.map(roleOf);

const DRAW = 3, ACC_T = 3, TURN_T = 3.2, ACC = 5.2, TOWER_T = 5; // :32
const TOWER = [ // :33-43
  "M325 655 L755 655",
  "M325 655 L325 330 L755 330 L755 655",
  "M318 330 L762 330 L762 320 L318 320 Z",
  "M395 320 L395 305 L685 305 L685 320",
  "M430 305 L410 245 L670 245 L650 305 Z",
  "M485 305 L475 245 M540 305 L540 245 M595 305 L605 245",
  "M402 245 L402 212 L678 212 L678 245 Z",
  "M552 212 L552 196 L572 196 L572 212 M548 196 a14 14 0 1 1 28 0 Z",
  "M450 212 L450 150 M640 212 L640 190",
];
// When each element draws on, in Draw's seconds (vector-scene.jsx:44-53):
// the buildings one after another, left to right; the runway strip
// together; the rest alongside.
const WIN = (() => {
  const SKY = DRAW - 0.4;
  const nb = ELS.filter((e) => e.b).length, nr = ELS.filter((e) => e.rw).length, m = ELS.length - nb - nr;
  let bi = 0, ri = 0, oi = 0;
  return ELS.map((e) => {
    if (e.b) { const s = (bi++ / nb) * SKY; return [s, s + SKY / nb]; }
    if (e.rw) { const s = (ri++ / nr) * DRAW * 0.25; return [s, DRAW]; }
    const s = (oi++ / Math.max(m, 1)) * SKY * 0.6;
    return [s, s + SKY * 0.4];
  });
})();
const WB = [430, 485, 540, 595, 650], WT = [410, 475, 540, 605, 670]; // the cab's window posts, :98

// The scene's colours from the page's palette (theme.js colours()), by the
// plan's table (phase G, "What was checked"), for vector-scene.jsx:16's
// KCGX object. The runway's edges are --alarm, WOPR's red; AMBER and
// MATRIX make that white, the brightest line in a one-colour picture, and
// there they are --frame, the screens' own edge. The window panes are
// --pink at 60 % (the original's darker violet), --pink, --cyan and --amber.
const WHITE = new Set(["#fff", "#ffffff", "white"]);
export function paletteOf(c) {
  return {
    sky: c.cyan, horizon: c.dim, dome: c.pink, edge: WHITE.has(c.alarm.toLowerCase()) ? c.frame : c.alarm, center: c.blue,
    thresh: c.white, tower: c.white, letters: c.white, lights: c.amber, panes: c.amber,
    win: [[c.pink, 0.6], [c.pink, 1], [c.cyan, 1], [c.amber, 1]],
  };
}

// A palette colour (#rgb or #rrggbb, as the stylesheet writes them) at an
// alpha, as rgba().
function withAlpha(colour, alpha) {
  let hex = colour.replace("#", "");
  if (hex.length === 3) hex = [...hex].map((h) => h + h).join("");
  const n = parseInt(hex, 16);
  if (hex.length !== 6 || Number.isNaN(n)) return colour;
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Path2D and the length of each `d`, made once (the runway's three are new
// strings every frame of the roll, but they are drawn on only during Draw,
// before the roll starts, so only the first of each is measured). A length
// is the SVG engine's own, from a detached <path>.
const paths = new Map();
function pathOf(d) {
  let p = paths.get(d);
  if (!p) {
    p = { path: new Path2D(d), length: null };
    if (paths.size < 256) paths.set(d, p);
  }
  return p;
}
const SVG = "http://www.w3.org/2000/svg";
let ruler = null;
function lengthOf(p, d) {
  if (p.length === null) {
    if (!ruler) ruler = document.createElementNS(SVG, "path");
    ruler.setAttribute("d", d);
    p.length = ruler.getTotalLength();
  }
  return p.length;
}

// The view (vector-scene.jsx:126): the scene's 1440 by 810 from x = -180,
// as large as fits the canvas, centred (an <svg>'s viewBox, xMidYMid meet);
// what lies outside it shows where the canvas is wider or taller.
export function fit(width, height) {
  const s = Math.min(width / 1440, height / 810);
  return { s, x: (width - 1440 * s) / 2 + 180 * s, y: (height - 810 * s) / 2 };
}

// One stroke, drawn on to `p` (0 to 1) of its length where p < 1, as the
// original's pathLength 1 and a dash offset (vector-scene.jsx:79, :90).
// A canvas restarts the dash at each subpath, as Chromium's SVG does.
function stroke(ctx, d, colour, { p = 1, alpha = 1, width = 1.6, dash = null } = {}) {
  if (alpha <= 0) return;
  const one = pathOf(d);
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = colour;
  ctx.shadowColor = colour;
  ctx.lineWidth = width;
  if (dash) {
    ctx.setLineDash(dash);
    ctx.lineDashOffset = 0;
  } else if (p < 1) {
    const length = lengthOf(one, d);
    ctx.setLineDash([length, length]);
    ctx.lineDashOffset = length * (1 - p);
  } else {
    ctx.setLineDash([]);
  }
  ctx.stroke(one.path);
}

// The scene at T (authored seconds), on the whole canvas, which the caller
// has cleared or faded. `colours` is theme.js's; `glow` the blur in CSS px
// and `ratio` the canvas's pixels a CSS px, for the shadows, which are in
// canvas pixels; `font` the family for KCGX, or nothing until the fonts are
// in (the letters wait). With `scale` and `size`, the scene is placed as on
// a canvas of `size` ([width, height]) and drawn `scale` times as large: a
// copy of that canvas's picture at another size, in register with it once
// scaled back. vector-scene.jsx:54-118.
export function frame(ctx, T, colours, { glow = 0, ratio = 1, font = null, scale = 1, size = null } = {}) {
  const pal = paletteOf(colours);
  const view = fit(...(size || [ctx.canvas.width, ctx.canvas.height]));
  const base = () => ctx.setTransform(view.s * scale, 0, 0, view.s * scale, view.x * scale, view.y * scale);
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.shadowBlur = glow * ratio;

  // The roll and the turn (vector-scene.jsx:55-64).
  const tA = T - CUES.Takeoff;
  const tc = clamp(tA, 0, ACC_T + TURN_T);
  const vEnd = (ACC * ACC_T) / 2;
  const s = tc < ACC_T ? (ACC * tc * tc * tc) / (6 * ACC_T) : (ACC * ACC_T * ACC_T) / 6 + vEnd * (tc - ACC_T);
  const R = runway(s);
  const z = 1 + 0.05 * Math.pow(clamp(tA / ACC_T, 0, 1), 2);
  const e = MOTION.turn(clamp((T - CUES.Turn) / TURN_T, 0, 1));
  const L = (a, b) => a + (b - a) * e;
  const du = clamp(tA / 1.8, 0, 1), dip = 15 * Math.sin(Math.PI * (1 - (1 - du) * (1 - du)));
  const world = () => {
    base();
    ctx.translate(0, dip);
    ctx.translate(L(545, 540), L(410, 405));
    ctx.rotate((-5 * Math.sin(Math.PI * e) * Math.PI) / 180);
    ctx.scale(L(z, 1.7), L(z, 1.7));
    ctx.translate(-L(545, 102), -L(410, 314));
  };

  // The skyline, the horizon and the dome, fading with the turn; then the
  // runway strip, dropping away under it (vector-scene.jsx:65-84, :115).
  const dt = T - CUES.Draw;
  const draw = (i, group) => {
    const el = ELS[i];
    const [ws, we] = WIN[i];
    const raw = clamp((dt - ws) / (we - ws), 0, 1);
    if (raw <= 0) return;
    const d = el.run ? R[el.run] : el.d;
    if (!d) return;
    const own = el.alpha ?? 1;
    const colour = pal[ROLES[i]];
    if (el.dash) {
      stroke(ctx, d, colour, { alpha: group * own * (Math.ceil(raw * 4) / 4), width: el.width, dash: el.dash });
    } else {
      const p = raw < 1 ? (el.b ? MOTION.line : MOTION.draw)(raw) : 1;
      stroke(ctx, d, colour, { p, alpha: group * own, width: el.width });
    }
  };
  world();
  if (e < 1) ELS.forEach((el, i) => { if (!el.rw) draw(i, 1 - e); });
  ctx.translate(0, 260 * e);
  ELS.forEach((el, i) => { if (el.rw) draw(i, 1); });

  // The tower, KCGX on its face and the cab's windows lighting, then all of
  // it rising and growing as it fades (vector-scene.jsx:85-105, :116).
  const tt = T - CUES.Tower, tl = T - CUES.Lights;
  const oz = Math.pow(clamp((T - CUES.Outro) / 5, 0, 1), 3);
  const of = MOTION.turn(clamp((T - CUES.Outro) / 5, 0, 1));
  const shown = 1 - of;
  if (tt > 0 && shown > 0) {
    base();
    ctx.translate(540, 275 + 130 * oz);
    ctx.scale(1 + 2 * oz, 1 + 2 * oz);
    ctx.translate(-540, -275);
    for (let i = 0; i < 4; i++) { // the panes, :98-103
      const p = MOTION.draw(clamp((tl - i * 0.8) / 1.6, 0, 1));
      if (p <= 0) continue;
      const [colour, part] = pal.win[i];
      const x = WB[i];
      ctx.globalAlpha = shown * 0.65 * p * part;
      ctx.fillStyle = colour;
      ctx.shadowColor = colour;
      ctx.fill(pathOf(`M${x + 2} 303 L${WT[i] + 2} 247 L${WT[i + 1] - 2} 247 L${WB[i + 1] - 2} 303 Z`).path);
    }
    TOWER.forEach((d, i) => { // the tower, line by line, :86-91
      const s0 = (i / TOWER.length) * TOWER_T * 0.45, s1 = s0 + TOWER_T * 0.15;
      const p = MOTION.draw(clamp((tt - s0) / (s1 - s0), 0, 1));
      if (p > 0) stroke(ctx, d, pal.tower, { p, alpha: shown });
    });
    if (font) { // KCGX, letter by letter, :92-97
      ctx.font = `160px ${font}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.lineWidth = 1.6;
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      "KCGX".split("").forEach((ch, i) => {
        const p = MOTION.draw(clamp((tl - i * 0.8) / 1.6, 0, 1));
        if (p <= 0) return;
        // The letter's fade is in its colour: WebKit strokes text with a
        // shadow at full alpha whatever globalAlpha says.
        ctx.strokeStyle = ctx.shadowColor = withAlpha(pal.letters, shown * p);
        ctx.strokeText(ch, 540 + (i - 1.5) * 90, 548);
      });
    }
  }
  ctx.restore();
}
