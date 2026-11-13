// The moving layer (spec, Radar; Rendering): aircraft, their trails and
// flight tags, and the focus ring, drawn every frame onto `radar.trace` and
// dead reckoned between polls from ground speed and track.
//
// The glow is a canvas shadow, and a shadow costs by the draw, not by the
// pixel: with one on every trail segment and chevron, WebKit, and Chromium
// drawing on a GPU, took 2 ms an aircraft a frame. So the aircraft's lines
// are drawn bare on a third canvas (`radar.bare`), a colour at a time, and
// that canvas is drawn onto the moving layer once with the shadow on.
//
// `radar` is the shared state `mountRadar` makes (see radar/index.js);
// `init` adds this module's part of it.

import { glowBlur } from "../theme.js";
import { focus } from "../focus.js";
import { FONT, claim, inked, trailing } from "./draw.js";
import { toScreen } from "./view.js";

const DIM_ALPHA = 0.15;
const STALE_FADE_FROM = 30; // seconds without a position before an aircraft fades
const EMERGENCY = new Set(["7500", "7600", "7700"]);
const TAG_PX = 16; // a flight tag's text,
const TAG_STEP_PX = 18; // and from one of its lines down to the next

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

// The layer's two canvases, and what its last drawing left: the aircraft
// where they were reckoned to be, and for the pointer what is where.
export function init(radar) {
  radar.trace = document.createElement("canvas"); // the moving layer, for persistence
  radar.bare = document.createElement("canvas"); // the aircraft's lines in one colour, before their glow
  radar.canvases.push(radar.trace, radar.bare);
  radar.now = []; // [{ ...ac, now: [x, y] in nm, age }], as last drawn
  radar.hits = []; // [{ hex, x, y, tag: {lines, ...label} or null, trail: [[x, y]] }]
  return {
    debug: () => ({ hits: radar.hits.map((h) => ({ hex: h.hex, x: h.x, y: h.y, tag: h.tag })) }),
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

// Draws the aircraft onto `ctx` and returns them, with the boxes their tags
// are to stand on: [{ box, colour, alpha }], each as dim as its aircraft.
// The boxes cannot be drawn here; `frame` puts them under this layer.
// Leaves `radar.now` holding the aircraft as drawn, and `radar.hits`
// saying what is where, for the pointer.
export function drawMoving(radar, ctx, width, height, ratio, s, c, prefs) {
  const { store, project, bare, hits, now: list } = radar;
  hits.length = 0;
  const boxes = [];
  const step = TAG_STEP_PX * ratio;
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

  // The tags, over every aircraft's lines and without a glow. A tag is up
  // and right of its chevron. Its last line is where the one line has
  // always been; a line above it stands higher.
  ctx.save();
  ctx.font = `${TAG_PX * ratio}px ${FONT}`;
  ctx.letterSpacing = `${1.5 * ratio}px`;
  for (const { ac, colour, alpha, head, points } of seen) {
    const lines = tagLines(ac, prefs.tag_fields);
    let tag = null;
    if (lines.length) {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = colour;
      const left = head[0] + 14 * ratio;
      const first = head[1] - 10 * ratio - (lines.length - 1) * step; // the top line's baseline
      let w = 0;
      lines.forEach((line, i) => {
        w = Math.max(w, ctx.measureText(line).width);
        ctx.fillText(line, left, first + i * step);
      });
      const text = { x: left, y: first - 16 * ratio, w, h: 20 * ratio + (lines.length - 1) * step };
      const ink = inked(left, first, w - trailing(1.5 * ratio), TAG_PX * ratio, lines.length, step);
      tag = { lines, ...claim(text, ink, radar.boxed("AIRCRAFT"), ratio, prefs) };
      if (tag.box) boxes.push({ box: tag.box, colour, alpha });
    }
    hits.push({ hex: ac.hex, x: head[0], y: head[1], tag, trail: points });
  }
  ctx.restore();
  return { list, boxes };
}
