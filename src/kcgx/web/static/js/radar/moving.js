// The moving layer (spec, Radar; Rendering): aircraft, their trails and
// flight tags, and the focus ring, drawn every frame and dead reckoned
// between polls from ground speed and track.
//
// The aircraft's lines go onto `radar.trace`, which is added to the map and
// fades rather than clears when the display persists. Their tags go onto a
// layer of their own, `radar.tags`, cleared every frame and laid over
// everything else as it is, not added (phase G decision 8): a tag and its
// box sit over map lines, other aircraft and other trails, and leave no
// persistence trail of their own. On it the tags go down in rank order,
// the sort's last first, so that its first (and the focused aircraft,
// always) is on top: each its box, then its letters over the box.
//
// The glow is a canvas shadow, and a shadow costs by the draw, not by the
// pixel: with one on every trail segment and chevron, WebKit, and Chromium
// drawing on a GPU, took 2 ms an aircraft a frame. So the aircraft's lines
// are drawn bare on a third canvas (`radar.bare`), a colour at a time, and
// that canvas is drawn onto the moving layer once with the shadow on. The
// tags' letters, unboxed, glow from the same canvas a colour at a time,
// under every tag (the tags following over it in rank order), only the
// shadow drawn and only about the letters. Boxed ("AIRCRAFT" in
// prefs.box_items, and the boxes filled or edged), a tag glows by itself,
// its letters drawn with the shadow on, after its own box: a box never
// hides its own letters' glow, and a tag's glow is cut only by the boxes
// over it.
//
// `radar` is the shared state `mountRadar` makes (see radar/index.js);
// `init` adds this module's part of it.
//
// What the pointer (view.js's hit test) may read, as the last frame left it:
//
//   radar.hits[]     { hex, x, y, tag, trail } an aircraft: its chevron at
//                    (x, y), canvas px; `trail` its points, newest first.
//   hits[].tag       null when it has no tag, else { lines, x, y, w, h,
//                    boxed, box }: x..h is all it claims (text and, when
//                    boxed, box); `boxed` whether it is; `box` the box as
//                    painted, { x, y, w, h } on whole pixels, or null.
//   radar.tagOrder   hexes, in the order the tags were drawn: BOTTOM FIRST,
//                    the one on top last. A hit test wanting the tag on top
//                    reads it from the end; a filled box hides what is
//                    under it, chevrons and the tags further down included.

import { glowBlur } from "../theme.js";
import { focus } from "../focus.js";
import { FONT, claim, inked, paintBox, trailing } from "./draw.js";
import { labelPx } from "./still.js";
import { toScreen } from "./view.js";

const DIM_ALPHA = 0.15;
const STALE_FADE_FROM = 30; // seconds without a position before an aircraft fades
const EMERGENCY = new Set(["7500", "7600", "7700"]);
const TAG_PX = 16; // the text size the tag's spacings are given for (prefs.tag_px scales them),
const TAG_STEP_PX = 18; // from one of its lines down to the next

// Where an aircraft will be `seconds` after its last position.
export function reckon(lat, lon, gs, trk, seconds) {
  if (!gs || trk === null || trk === undefined || seconds <= 0) return [lat, lon];
  const nm = (gs * seconds) / 3600;
  const b = (trk * Math.PI) / 180;
  const dlat = (nm * Math.cos(b)) / 60;
  const dlon = (nm * Math.sin(b)) / (60 * Math.max(0.01, Math.cos((lat * Math.PI) / 180)));
  return [lat + dlat, lon + dlon];
}

// -- this module's part of `radar` -------------------------------------------------

// The layer's three canvases, and what its last drawing left: the aircraft
// where they were reckoned to be, for the pointer what is where, and the
// order the tags were laid in.
export function init(radar) {
  radar.trace = document.createElement("canvas"); // the aircraft's lines, for persistence
  radar.tags = document.createElement("canvas"); // their tags, over everything
  radar.bare = document.createElement("canvas"); // lines or letters in one colour, before their glow
  radar.canvases.push(radar.trace, radar.tags, radar.bare);
  radar.now = []; // [{ ...ac, now: [x, y] in nm, age }], as last drawn
  radar.hits = []; // [{ hex, x, y, tag: {lines, ...label} or null, trail: [[x, y]] }]
  radar.tagOrder = []; // the hexes whose tags were drawn, the one on top last
  return {
    debug: () => ({
      hits: radar.hits.map((h) => ({ hex: h.hex, x: h.x, y: h.y, tag: h.tag })),
      tag_order: [...radar.tagOrder],
    }),
  };
}

// -- flight tags -----------------------------------------------------------------

// The fields a tag can show (prefs.tag_fields), in the order it shows them:
// who the aircraft is, then what it is doing.
const given = (value) => value !== null && value !== undefined && value !== "";
const TAG_IDENTITY = [
  ["CALLSIGN", (ac) => ac.label],
  ["TYPE", (ac) => ac.type],
  ["SQWK", (ac) => ac.sq],
];
const TAG_NUMBERS = [
  ["ALT", (ac) => ac.alt], // feet, or "GND"
  ["GS", (ac) => (given(ac.gs) ? `${ac.gs}KT` : null)],
  ["TRK", (ac) => (given(ac.trk) ? `${String(ac.trk).padStart(3, "0")}°` : null)],
  ["DIST", (ac) => (given(ac.dist) ? `${ac.dist.toFixed(1)}NM` : null)],
];

// A tag's lines of text. One or two chosen fields share a line; more are
// identity over numbers. What the aircraft does not report is left out, and
// so is a line with nothing on it: no lines, no tag.
export function tagLines(ac, fields) {
  const chosen = (group) => group.filter(([field]) => fields.includes(field));
  const said = (group) => chosen(group).map(([, text]) => text(ac)).filter(given).map(String);
  const identity = said(TAG_IDENTITY);
  const numbers = said(TAG_NUMBERS);
  const together = chosen(TAG_IDENTITY).length + chosen(TAG_NUMBERS).length <= 2;
  const lines = together ? [[...identity, ...numbers]] : [identity, numbers];
  return lines.filter((line) => line.length).map((line) => line.join(" "));
}

// -- aircraft --------------------------------------------------------------------

function aircraftNow(radar) {
  const { store, project } = radar;
  const frame = store.state.radar;
  if (!frame || !project) return [];
  const since = (performance.now() - store.state.radarAt) / 1000;
  return frame.ac.map((ac) => {
    const age = ac.age + since;
    const [lat, lon] = reckon(ac.lat, ac.lon, ac.gs, ac.trk, age);
    return { ...ac, now: project(lat, lon), age };
  });
}

// One aircraft's lines, in the pen's colour and at its width: the trail,
// the chevron and, about the focused one, a ring.
function strokeAircraft(pen, { ac, isFocus, alpha, head, points }, ratio) {
  // The trail fades from full at the arrow to nothing at its oldest point.
  for (let i = 1; i < points.length; i += 1) {
    pen.globalAlpha = alpha * 0.95 * (1 - (i - 1) / (points.length - 1));
    pen.beginPath();
    pen.moveTo(points[i - 1][0], points[i - 1][1]);
    pen.lineTo(points[i][0], points[i][1]);
    pen.stroke();
  }
  pen.globalAlpha = alpha;
  // The chevron, pointing along track.
  pen.save();
  pen.translate(head[0], head[1]);
  pen.rotate(((ac.trk || 0) * Math.PI) / 180);
  pen.beginPath();
  const u = ratio;
  pen.moveTo(0, -9 * u); pen.lineTo(0, 9 * u);
  pen.moveTo(-7 * u, 4 * u); pen.lineTo(0, -9 * u); pen.lineTo(7 * u, 4 * u);
  pen.stroke();
  pen.restore();
  if (isFocus) {
    pen.save();
    pen.lineWidth = 1.4 * ratio;
    pen.beginPath();
    pen.arc(head[0], head[1], 16 * ratio, 0, Math.PI * 2);
    pen.stroke();
    pen.restore();
  }
}

// Draws the aircraft's lines onto `ctx` (the moving layer) and their tags
// onto `radar.tags`, and returns the aircraft. Leaves `radar.now` holding
// them as drawn, `radar.hits` saying what is where, for the pointer, and
// `radar.tagOrder` the order the tags went down in.
export function drawMoving(radar, ctx, width, height, ratio, s, c, prefs) {
  const { store, project, bare, hits, now: list } = radar;
  hits.length = 0;
  const focused = focus.hex;
  list.splice(0, list.length, ...aircraftNow(radar));
  if (focused && !list.some((ac) => ac.hex === focused)) focus.set(null);
  const seen = list.map((ac) => {
    const isFocus = ac.hex === focused;
    const colour = isFocus ? c.pink : EMERGENCY.has(ac.sq) ? c.alarm : c.cyan;
    const stale = Math.max(0, Math.min(1, (ac.age - STALE_FADE_FROM) / 30));
    let alpha = 1 - 0.7 * stale;
    if (focused && !isFocus) alpha *= DIM_ALPHA;
    const head = toScreen(radar, ac.now, s, width, height);
    const trail = (store.state.trails.get(ac.hex) || [])
      .map((p) => toScreen(radar, project(p.lat, p.lon), s, width, height))
      .reverse();
    return { ac, isFocus, colour, alpha, head, points: [head, ...trail] };
  });

  // The lines, a colour at a time: bare, then onto the layer under one
  // shadow, which is their glow. The focused aircraft's colour is last and
  // so on top. With no glow they go straight onto the layer.
  const blur = glowBlur() * ratio;
  const pen = blur ? bare.getContext("2d") : ctx;
  for (const colour of new Set([c.cyan, c.alarm, c.pink])) {
    const mine = seen.filter((one) => one.colour === colour);
    if (!mine.length) continue;
    if (blur) pen.clearRect(0, 0, width, height);
    pen.save();
    pen.lineWidth = 1.8 * ratio;
    pen.strokeStyle = colour;
    for (const one of mine) strokeAircraft(pen, one, ratio);
    pen.restore();
    if (!blur) continue;
    ctx.save();
    ctx.shadowColor = colour;
    ctx.shadowBlur = blur;
    ctx.drawImage(bare, 0, 0);
    ctx.restore();
  }

  drawTags(radar, seen, width, height, ratio, c, prefs, blur);
  return { list };
}

// -- flight tags, on their own layer ---------------------------------------------

// Where the sort puts an aircraft: 0 first to 1 last. One it has not
// ranked counts as first, and the focused aircraft is first whatever.
function rankOf(radar, one) {
  if (one.isFocus) return -Infinity;
  const rank = radar.store.state.rank.get(one.ac.hex);
  return rank === undefined ? 0 : rank;
}

// Each aircraft's tag: placed, measured and claimed for the pointer, then
// laid onto the cleared tags layer, the sort's last first, each its box,
// its glow (see the top of this file) and its letters. A tag is up and right of its
// chevron. Its last line is where the one line has always been; a line
// above it stands higher.
function drawTags(radar, seen, width, height, ratio, c, prefs, blur) {
  const { tags, bare, hits, tagOrder } = radar;
  const ctx = tags.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, width, height);
  // The text's size is prefs.tag_px, following the zoom (Task 10's
  // labelPx); its spacing and the room about it grow with it.
  const px = labelPx(prefs.tag_px, radar) * ratio;
  const k = px / ratio / TAG_PX;
  const step = TAG_STEP_PX * k * ratio;
  const font = `${px}px ${FONT}`;
  const spacing = 1.5 * k * ratio;
  const typeset = (pen) => { pen.font = font; pen.letterSpacing = `${spacing}px`; };

  ctx.save();
  typeset(ctx);
  const drawn = [];
  for (const one of seen) {
    const { ac, colour, alpha, head, points } = one;
    const lines = tagLines(ac, prefs.tag_fields);
    let tag = null;
    if (lines.length) {
      const left = head[0] + 14 * ratio;
      const first = head[1] - 10 * ratio - (lines.length - 1) * step; // the top line's baseline
      const w = Math.max(...lines.map((line) => ctx.measureText(line).width));
      const text = { x: left, y: first - 16 * k * ratio, w, h: 20 * k * ratio + (lines.length - 1) * step };
      const ink = inked(left, first, w - trailing(spacing), px, lines.length, step);
      tag = { lines, ...claim(text, ink, radar.boxed("AIRCRAFT"), ratio, prefs) };
      drawn.push({ one, lines, left, first, text, box: tag.box, colour, alpha, rank: rankOf(radar, one) });
    }
    hits.push({ hex: ac.hex, x: head[0], y: head[1], tag, trail: points });
  }
  ctx.restore();
  // The sort's last first; a stable sort keeps the frame's order in a tie.
  drawn.sort((a, b) => b.rank - a.rank);
  tagOrder.splice(0, tagOrder.length, ...drawn.map((d) => d.one.ac.hex));

  const letters = (pen, d) => {
    pen.globalAlpha = d.alpha;
    pen.fillStyle = d.colour;
    d.lines.forEach((line, i) => pen.fillText(line, d.left, d.first + i * step));
  };

  // Unboxed tags' letters' glow, in one colour: the letters bare, then only
  // their shadow onto the layer. The bare canvas is drawn a whole width off
  // to the left, and its shadow as far back to the right, onto the
  // letters' places, clipped to their text widened by twice the blur (which
  // holds all of the shadow): a blur costs by its area, and the shadow is
  // reckoned only within the clip. (Drawing only that part of the canvas,
  // drawImage's nine arguments, would do as well, but WebKit then draws no
  // shadow at all for an image put down wholly off the canvas.) The bare
  // canvas is empty before and after each: cleared once, and each time
  // where its letters went.
  const pen = bare.getContext("2d");
  const glowOf = (group, colour) => {
    const margin = 2 * blur;
    const x0 = Math.max(0, Math.floor(Math.min(...group.map((d) => d.text.x)) - margin));
    const y0 = Math.max(0, Math.floor(Math.min(...group.map((d) => d.text.y)) - margin));
    const x1 = Math.min(width, Math.ceil(Math.max(...group.map((d) => d.text.x + d.text.w)) + margin));
    const y1 = Math.min(height, Math.ceil(Math.max(...group.map((d) => d.text.y + d.text.h)) + margin));
    if (x1 <= x0 || y1 <= y0) return; // all off the canvas
    pen.save();
    typeset(pen);
    for (const d of group) letters(pen, d);
    pen.restore();
    ctx.save();
    ctx.beginPath();
    ctx.rect(x0, y0, x1 - x0, y1 - y0);
    ctx.clip();
    ctx.shadowColor = colour;
    ctx.shadowBlur = blur;
    ctx.shadowOffsetX = width;
    ctx.drawImage(bare, -width, 0);
    ctx.restore();
    pen.clearRect(x0, y0, x1 - x0, y1 - y0);
  };

  // Unboxed, the glow goes down a colour at a time under every tag. So it
  // does under boxes that paint nothing (no fill, no border), which leave
  // the picture as it was.
  const boxed = radar.boxed("AIRCRAFT") && (prefs.box_fill > 0 || prefs.box_border > 0);
  if (blur && !boxed) {
    pen.setTransform(1, 0, 0, 1, 0, 0);
    pen.clearRect(0, 0, width, height);
    for (const colour of new Set([c.cyan, c.alarm, c.pink])) {
      const mine = drawn.filter((d) => d.colour === colour);
      if (mine.length) glowOf(mine, colour);
    }
  }

  // Boxed, each tag's glow goes over its own box: its letters are drawn
  // with the shadow on, which puts the shadow down under them. That is a
  // shadowed draw a line, but small ones: a tag at a time from the bare
  // canvas, even clipped, cost Chromium and WebKit ten times as much.
  for (const d of drawn) {
    if (d.box) paintBox(ctx, d.box, d.colour, ratio, prefs, d.alpha);
    ctx.save();
    typeset(ctx);
    if (blur && boxed) { ctx.shadowColor = d.colour; ctx.shadowBlur = blur; }
    letters(ctx, d);
    ctx.restore();
  }
}
