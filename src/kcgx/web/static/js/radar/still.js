// The static layer (spec, Radar; Rendering): the map, the range rings, the
// home airport and its runways, places and state names. Drawn into an
// offscreen canvas (`radar.still`) once per airport, resize, pan, zoom,
// range, palette or hover change, and copied each frame by radar/index.js.
//
// The projection is azimuthal equidistant, centred on the airport, so range
// rings are true circles and distance reads straight off the screen.
//
// Two bare labels may cross, and both read; a box would hide the other
// label, so a boxed label is given room that no other label is in.
//
// `radar` is the shared state `mountRadar` makes (see radar/index.js);
// `init` adds this module's part of it.

import { colours, glowBlur, reducedMotion } from "../theme.js";
import { FONT, around, claim, inked, meets, paintBox, trailing } from "./draw.js";
import { recentre, scale, toScreen } from "./view.js";

const NM_PER_RADIAN = 3440.065;
const RING_STEPS_NM = [0.5, 1, 2, 5, 10, 20, 50];
const RINGS_IN_VIEW = 5; // at most this many between the centre and the nearer edge
const SMALL_AIRPORTS_NM = 27; // small airports show from this view inwards
const HOME_NM = 2.5; // the home ring's true size,
const HOME_MIN_PX = 24; // and what it is held between on screen
const HOME_MAX_PX = 64;
const RING_TEXT_PX = 12; // a ring's number,
const RING_GAP_PX = 4; // how far it stands off its ring and clear of the home ring,
const RING_APART_PX = 2; // and of another ring's number
const DRAW_ON_MS = 2000;
const LABEL_ALPHA = 0.4;
const VOR = new Set(["VOR", "VOR-DME", "VORTAC", "TACAN"]);
const SYMBOL_PX = 6; // a place's symbol reaches this far from its point
// The label box setting (prefs.box_items) that covers each kind of place.
const BOXED_AS = { navaid: "NAVAIDS", airport: "AIRPORTS", city: "CITIES", peak: "PEAKS" };

const DRAWN_ON = new Set(["coast", "lake", "river", "country", "state"]);

// A label's text height for a base size in px. For now the base itself;
// labels by zoom (Task 10) make it follow the view. That version needs the
// view and the prefs: it will take the radar's shared state as a second
// argument, `labelPx(base, radar)`.
export function labelPx(base) {
  return base;
}

// -- this module's part of `radar` -------------------------------------------------

// The map and what the last drawing of the layer left for the pointer and
// for tests, and the layer's canvas. A new airport is a new map and a new
// picture: the view goes back to the whole range about it.
export function init(radar) {
  radar.still = document.createElement("canvas");
  radar.canvases.push(radar.still);
  radar.map = null; // decoded geo for the current airport
  radar.mapFor = "";
  radar.project = null;
  radar.drawOnFrom = 0;
  radar.hovered = null; // a placed label's key
  // A label is what `claim` gives: { x, y, w, h, boxed, box: {x, y, w, h} or null }.
  radar.placed = []; // [{ key, ...label }]
  radar.rings = []; // [{ nm, r, bright, text, label: {...label, at: [x, baseline]} or null }], as last drawn
  radar.home = { x: 0, y: 0, r: 0 }; // the airport and its ring, as last drawn
  radar.symbols = {}; // kind -> how many are on screen, as last drawn
  radar.store.subscribe((kind) => {
    const { airport } = radar.store.state;
    if (kind === "all" && airport && airport.icao !== radar.mapFor) {
      recentre(radar);
      loadMap(radar, airport);
    }
  });
  return {
    debug() {
      const { map } = radar;
      return {
        placed: [...radar.placed], hovered: radar.hovered, mapFor: radar.mapFor, loaded: Boolean(map),
        rings: [...radar.rings], home: { ...radar.home }, symbols: { ...radar.symbols },
        layers: map ? Object.fromEntries(Object.entries(map.lines).map(([k, v]) => [k, v.length])) : {},
      };
    },
  };
}

// -- the projection --------------------------------------------------------------

export function projector(lat0, lon0) {
  const p0 = (lat0 * Math.PI) / 180;
  const sin0 = Math.sin(p0);
  const cos0 = Math.cos(p0);
  return (lat, lon) => {
    const p = (lat * Math.PI) / 180;
    let dl = ((lon - lon0 + 540) % 360) - 180; // across the antimeridian too
    dl = (dl * Math.PI) / 180;
    const sinp = Math.sin(p);
    const cosp = Math.cos(p);
    const cosc = Math.max(-1, Math.min(1, sin0 * sinp + cos0 * cosp * Math.cos(dl)));
    const c = Math.acos(cosc);
    const k = c < 1e-9 ? 1 : c / Math.sin(c);
    const x = k * cosp * Math.sin(dl) * NM_PER_RADIAN;
    const y = k * (cos0 * sinp - sin0 * cosp * Math.cos(dl)) * NM_PER_RADIAN;
    return [x, -y]; // nm east, nm south: screen orientation
  };
}

// -- the map, decoded once per airport -------------------------------------------

function decode(geo, project) {
  const q = geo.q;
  const lines = {};
  for (const [layer, pieces] of Object.entries(geo.lines)) {
    lines[layer] = pieces.map((piece) => {
      const out = new Float32Array(piece.length);
      let x = piece[0];
      let y = piece[1];
      for (let i = 0; i < piece.length; i += 2) {
        if (i) { x += piece[i]; y += piece[i + 1]; }
        const [px, py] = project(y / q, x / q);
        out[i] = px;
        out[i + 1] = py;
      }
      return out;
    });
  }
  const at = (row) => project(row[1] / q, row[0] / q);
  const points = {};
  for (const [kind, rows] of Object.entries(geo.points)) points[kind] = rows.map((row) => ({ xy: at(row), row }));
  const labels = {};
  for (const [kind, rows] of Object.entries(geo.labels)) labels[kind] = rows.map((row) => ({ xy: at(row), row }));
  const runways = geo.runways.map((r) => [project(r[1] / q, r[0] / q), project(r[3] / q, r[2] / q)]);
  return { lines, points, labels, runways };
}

export async function loadMap(radar, airport) {
  const key = airport.icao;
  radar.mapFor = key;
  radar.map = null;
  radar.project = airport.lat === null ? null : projector(airport.lat, airport.lon);
  radar.staticDirty = true;
  if (!radar.project) return;
  try {
    const response = await fetch(`/api/geo?icao=${encodeURIComponent(key)}`);
    if (!response.ok) throw new Error(`${response.status}`);
    const geo = await response.json();
    if (radar.mapFor !== key) return; // the airport changed while we were asking
    radar.map = decode(geo, radar.project);
    radar.drawOnFrom = reducedMotion() ? 0 : performance.now();
    radar.staticDirty = true;
  } catch {
    radar.map = null;
  }
}

// -- rings -----------------------------------------------------------------------

// The home ring is 2.5 nm, held between two sizes on screen so that it
// neither vanishes at a wide view nor fills a close one.
function homeRing(s, ratio) {
  return Math.min(HOME_MAX_PX * ratio, Math.max(HOME_MIN_PX * ratio, HOME_NM * s));
}

// Which rings cross the screen: every multiple of a 1, 2, 5 step short of
// the range, and the range itself whether or not it is a multiple. The
// step is the smallest that puts no more than five between the centre and
// the nearer edge.
function ringsOn(radar, centre, s, width, height) {
  if (s <= 0) return [];
  const dx = Math.max(0, -centre[0], centre[0] - width);
  const dy = Math.max(0, -centre[1], centre[1] - height);
  const nearest = Math.hypot(dx, dy) / s; // nm from the airport to the screen
  const farthest = Math.hypot(
    Math.max(centre[0], width - centre[0]), Math.max(centre[1], height - centre[1]),
  ) / s;
  const limit = radar.range();
  const step = RING_STEPS_NM.find((nm) => radar.view.nm / nm <= RINGS_IN_VIEW) || RING_STEPS_NM[RING_STEPS_NM.length - 1];
  const out = [];
  const ring = (nm, bright) => out.push({ nm, r: nm * s, bright, text: `${Number(nm.toFixed(2))}`, label: null });
  const last = Math.floor(Math.min(limit, farthest) / step);
  for (let i = Math.max(1, Math.ceil(nearest / step)); i <= last; i += 1) {
    if (i * step < limit) ring(i * step, false);
  }
  if (limit >= nearest && limit <= farthest) ring(limit, true);
  return out;
}

// Where a ring's number goes: just outside the ring, on the north east
// diagonal while the airport is on the screen and, once it is panned off,
// where the ring passes nearest the middle of the screen. Either gives way
// to the other when it is off the screen, on the home ring or on `name`,
// the airport's name, which is given only when it or the numbers are
// boxed: bare, the two cross as they always have. null when neither has
// room, or when the number would touch one of `numbered`, those already
// placed. A boxed number needs the room for its box.
function ringLabel(radar, ctx, ring, centre, width, height, ratio, clear, numbered, name) {
  const w = ctx.measureText(ring.text).width;
  const h = RING_TEXT_PX * ratio;
  const gap = RING_GAP_PX * ratio;
  const apart = RING_APART_PX * ratio;
  const ways = [[Math.SQRT1_2, -Math.SQRT1_2]];
  const dx = width / 2 - centre[0];
  const dy = height / 2 - centre[1];
  const far = Math.hypot(dx, dy);
  if (far > 1) ways.push([dx / far, dy / far]);
  if (centre[0] < 0 || centre[1] < 0 || centre[0] > width || centre[1] > height) ways.reverse();
  for (const [ux, uy] of ways) {
    const x = centre[0] + ring.r * ux;
    const y = centre[1] + ring.r * uy;
    // In the quarter that faces away from the airport, so never across the ring.
    const text = { x: ux >= 0 ? x + gap : x - gap - w, y: uy <= 0 ? y - gap - h : y + gap, w, h };
    const at = [text.x, text.y + h];
    const l = claim(text, inked(at[0], at[1], w, h), radar.boxed("RINGS"), ratio, radar.store.state.prefs);
    if (l.x < 0 || l.y < 0 || l.x + l.w > width || l.y + l.h > height) continue;
    const nearX = Math.max(l.x - centre[0], 0, centre[0] - l.x - l.w);
    const nearY = Math.max(l.y - centre[1], 0, centre[1] - l.y - l.h);
    if (Math.hypot(nearX, nearY) < clear) continue;
    if (name && meets(l, name)) continue;
    const touches = numbered.some((n) => (
      l.x < n.x + n.w + apart && n.x < l.x + l.w + apart && l.y < n.y + n.h + apart && n.y < l.y + l.h + apart
    ));
    return touches ? null : { ...l, at };
  }
  return null;
}

// -- the layer -------------------------------------------------------------------

function strokeLines(radar, ctx, lines, s, width, height, progress) {
  ctx.beginPath();
  const ox = width / 2 - radar.view.panX * s;
  const oy = height / 2 - radar.view.panY * s;
  for (const line of lines) {
    const n = line.length / 2;
    const upto = progress >= 1 ? n : Math.max(2, Math.ceil(n * progress));
    ctx.moveTo(ox + line[0] * s, oy + line[1] * s);
    for (let i = 1; i < upto; i += 1) ctx.lineTo(ox + line[2 * i] * s, oy + line[2 * i + 1] * s);
  }
  ctx.stroke();
}

function glow(ctx, colour, ratio) {
  ctx.shadowColor = colour;
  ctx.shadowBlur = glowBlur() * ratio;
}

export function drawStatic(radar, now) {
  const { ratio, width, height } = radar.size();
  const ctx = radar.still.getContext("2d");
  const c = colours();
  const { prefs } = radar.store.state;
  const { map } = radar;
  const s = scale(radar, width, height, ratio);
  const centre = toScreen(radar, [0, 0], s, width, height);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.globalCompositeOperation = "lighter";
  const progress = radar.drawOnFrom ? Math.min(1, (now - radar.drawOnFrom) / DRAW_ON_MS) : 1;

  if (map) {
    const layers = [
      ["airway", c.blue, 1.2, [3 * ratio, 6 * ratio], 0.7],
      ["state", c.dim, 1, [], 0.55],
      ["country", c.green, 1.2, [6 * ratio, 4 * ratio], 0.9],
      ["river", c.cyan, 1, [], 0.5],
      ["lake", c.cyan, 1.2, [], 0.75],
      ["coast", c.cyan, 1.8, [], 1],
      ["airspace_d", c.alarm, 1, [3 * ratio, 5 * ratio], 0.45],
      ["airspace_c", c.alarm, 1.3, [5 * ratio, 5 * ratio], 0.8],
      ["airspace_b", c.alarm, 1.4, [5 * ratio, 5 * ratio], 0.9],
    ];
    for (const [layer, colour, w, dash, alpha] of layers) {
      const lines = map.lines[layer];
      if (!lines || !lines.length) continue;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = colour;
      ctx.lineWidth = w * ratio;
      ctx.setLineDash(dash);
      glow(ctx, colour, ratio);
      strokeLines(radar, ctx, lines, s, width, height, DRAWN_ON.has(layer) ? progress : 1);
      ctx.restore();
    }
  }

  // Range rings, dim, and the range itself, bright. Each is numbered where
  // there is room; the range's number is placed first, so a dim ring's
  // that would touch it is the one left off. The airport's name has its
  // place before any of them: a box under it, or under a number, is not to
  // be drawn across the other.
  const { rings } = radar;
  rings.splice(0, rings.length, ...ringsOn(radar, centre, s, width, height));
  const name = homeName(radar, ctx, centre, s, ratio, prefs);
  const keepOff = name && (radar.boxed("HOME") || radar.boxed("RINGS")) ? name.label : null;
  ctx.save();
  ctx.strokeStyle = c.cyan;
  ctx.lineWidth = ratio;
  glow(ctx, c.cyan, ratio);
  for (const ring of rings) {
    ctx.globalAlpha = ring.bright ? 0.8 : 0.35;
    ctx.beginPath();
    ctx.arc(centre[0], centre[1], ring.r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
  ctx.save();
  ctx.fillStyle = c.dim;
  ctx.font = `${RING_TEXT_PX * ratio}px ${FONT}`;
  const clear = homeRing(s, ratio) + RING_GAP_PX * ratio;
  const numbered = [];
  for (const ring of [...rings.filter((r) => r.bright), ...rings.filter((r) => !r.bright)]) {
    ring.label = ringLabel(radar, ctx, ring, centre, width, height, ratio, clear, numbered, keepOff);
    if (!ring.label) continue;
    numbered.push(ring.label);
    if (ring.label.box) paintBox(ctx, ring.label.box, c.dim, ratio, prefs);
    ctx.fillText(ring.text, ring.label.at[0], ring.label.at[1]);
  }
  ctx.restore();

  // The home airport first, so its name is reserved before any place
  // looks for room.
  radar.placed.length = 0;
  for (const kind of Object.keys(radar.symbols)) delete radar.symbols[kind];
  Object.assign(radar.home, { x: centre[0], y: centre[1], r: homeRing(s, ratio) });
  if (name) drawHome(radar, ctx, centre, s, ratio, c, prefs, name);
  if (map) drawPlaces(radar, ctx, s, width, height, ratio, c, prefs);
  radar.staticDirty = progress < 1;
}

// Symbols and labels, placed greedily by priority so no two labels
// overlap; a label that does not fit is left off, its symbol stays. Every
// label is given its place before anything is drawn, so that the boxes can
// go down first: a box hides the map under it, never a symbol or a name.
function drawPlaces(radar, ctx, s, width, height, ratio, c, prefs) {
  const { map, placed, symbols, rings } = radar;
  const boxed = radar.boxed;
  const onScreen = ([x, y]) => x > -40 && y > -40 && x < width + 40 && y < height + 40;
  const items = [];
  for (const { xy, row } of map.points.navaid || []) {
    if (!VOR.has(row[3])) continue;
    items.push({ kind: "navaid", xy, text: row[2], colour: c.cyan, priority: 30 });
  }
  for (const { xy, row } of map.points.airport || []) {
    if (row[3] === "small" && radar.view.nm > SMALL_AIRPORTS_NM) continue;
    items.push({ kind: "airport", xy, text: row[2], colour: c.cyan, priority: row[3] === "large" ? 25 : row[3] === "medium" ? 35 : 60 });
  }
  for (const { xy, row } of map.points.city || []) {
    items.push({ kind: "city", xy, text: row[2], colour: c.amber, priority: row[3] });
  }
  for (const { xy, row } of map.points.peak || []) {
    items.push({ kind: "peak", xy, text: row[2], colour: c.amber, priority: 20 });
  }
  items.sort((a, b) => a.priority - b.priority);

  // The home airport's own name and ring are reserved first. So are the
  // rings' numbers, from a label that is boxed and from every label once
  // the numbers are: a box is not to be drawn across a number, nor a
  // number's across a name. Bare, the two cross as they always have.
  const home = toScreen(radar, [0, 0], s, width, height);
  const clear = homeRing(s, ratio) + 2 * ratio;
  const taken = [{ x: home[0] - clear, y: home[1] - clear, w: 2 * clear, h: 2 * clear }, ...placed];
  const numbers = rings.filter((ring) => ring.label).map((ring) => ring.label);
  const numbersBoxed = boxed("RINGS");
  const free = (r) => (
    !taken.some((t) => meets(r, t)) && !((r.boxed || numbersBoxed) && numbers.some((n) => meets(r, n)))
  );
  // The label's place if there is room for it, which is then taken.
  const place = (key, label) => {
    if (!free(label)) return null;
    taken.push(label);
    placed.push({ key, ...label });
    return label;
  };

  ctx.save();
  ctx.lineWidth = 1.3 * ratio;
  const placeFont = () => { ctx.font = `${13 * ratio}px ${FONT}`; ctx.letterSpacing = `${1.5 * ratio}px`; };
  const stateFont = () => { ctx.font = `${14 * ratio}px ${FONT}`; ctx.letterSpacing = `${6 * ratio}px`; };

  placeFont();
  const places = []; // [{ item, p, key, baseline, label or null }]
  const reach = SYMBOL_PX * ratio;
  for (const item of items) {
    const p = toScreen(radar, item.xy, s, width, height);
    if (!onScreen(p)) continue;
    // Airports within the home ring are the home airport itself.
    if (item.kind === "airport" && Math.hypot(p[0] - home[0], p[1] - home[1]) < 8 * ratio) continue;
    symbols[item.kind] = (symbols[item.kind] || 0) + 1;
    const w = ctx.measureText(item.text).width;
    const h = 13 * ratio;
    const text = { x: p[0] + 8 * ratio, y: p[1] - h / 2 - 2 * ratio, w, h: h + 4 * ratio };
    const baseline = p[1] + h / 2 - 2 * ratio;
    // A place's box takes in its symbol: the two are one thing.
    const ink = around(
      inked(text.x, baseline, w - trailing(1.5 * ratio), h),
      { x: p[0] - reach, y: p[1] - reach, w: 2 * reach, h: 2 * reach },
    );
    const key = `${item.kind}:${item.text}`;
    const label = place(key, claim(text, ink, boxed(BOXED_AS[item.kind]), ratio, prefs));
    places.push({ item, p, key, baseline, label });
  }

  // State names: large, spaced, dim, and the first thing given up.
  stateFont();
  const states = []; // [{ name, key, x, baseline, label }]
  for (const { xy, row } of map.labels.state || []) {
    const p = toScreen(radar, xy, s, width, height);
    if (!onScreen(p)) continue;
    const w = ctx.measureText(row[2]).width;
    const text = { x: p[0] - w / 2, y: p[1] - 10 * ratio, w, h: 18 * ratio };
    const baseline = p[1] + 5 * ratio;
    const ink = inked(text.x, baseline, w - trailing(6 * ratio), 14 * ratio);
    const key = `state:${row[2]}`;
    const label = place(key, claim(text, ink, boxed("STATES"), ratio, prefs));
    if (label) states.push({ name: row[2], key, x: text.x, baseline, label });
  }

  // A box keeps its strength while its label brightens under the pointer.
  for (const { item, label } of places) if (label && label.box) paintBox(ctx, label.box, item.colour, ratio, prefs);
  for (const { label } of states) if (label.box) paintBox(ctx, label.box, c.dim, ratio, prefs);

  placeFont();
  for (const { item, p, key, baseline, label } of places) {
    ctx.globalAlpha = 0.85;
    ctx.strokeStyle = item.colour;
    glow(ctx, item.colour, ratio);
    symbol(ctx, item.kind, p, ratio);
    if (!label) continue;
    ctx.shadowBlur = 0;
    ctx.globalAlpha = radar.hovered === key ? 1 : LABEL_ALPHA;
    ctx.fillStyle = item.colour;
    ctx.fillText(item.text, p[0] + 8 * ratio, baseline);
  }

  stateFont();
  ctx.shadowBlur = 0;
  ctx.fillStyle = c.dim;
  for (const { name, key, x, baseline } of states) {
    ctx.globalAlpha = radar.hovered === key ? 1 : LABEL_ALPHA;
    ctx.fillText(name, x, baseline);
  }
  ctx.restore();
}

function symbol(ctx, kind, [x, y], ratio) {
  const r = 6 * ratio;
  ctx.beginPath();
  if (kind === "navaid") {
    ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath();
    ctx.rect(x - 2.5 * ratio, y - 2.5 * ratio, 5 * ratio, 5 * ratio);
  } else if (kind === "airport") {
    ctx.moveTo(x, y - r); ctx.lineTo(x + r, y + r * 0.85); ctx.lineTo(x - r, y + r * 0.85); ctx.closePath();
  } else if (kind === "peak") {
    ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.9, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r * 0.9, y); ctx.closePath();
  } else {
    ctx.arc(x, y, 3.5 * ratio, 0, Math.PI * 2);
  }
  ctx.stroke();
}

// -- home ------------------------------------------------------------------------

// Where the home airport's name goes: large, above and right of the ring
// on a short leader, as the film labels its bases. Worked out before
// anything of it is drawn, for the ring numbers that have to keep off it.
// null while there is no airport.
function homeName(radar, ctx, centre, s, ratio, prefs) {
  const airport = radar.store.state.airport;
  if (!airport) return null;
  const ring = homeRing(s, ratio);
  const lines = nameLines(airport);
  const size = 30 * ratio;
  const step = size + 2 * ratio;
  const foot = [centre[0] + ring * 0.7, centre[1] - ring * 0.7];
  const x = foot[0] + 12 * ratio;
  const last = foot[1] - 14 * ratio; // the bottom line's baseline
  const top = last - (lines.length - 1) * step;
  const font = `${size}px ${FONT}`;
  const spacing = 3 * ratio;
  ctx.save();
  ctx.font = font;
  ctx.letterSpacing = `${spacing}px`;
  let widest = 0;
  for (const line of lines) widest = Math.max(widest, ctx.measureText(line).width);
  ctx.restore();
  const text = { x, y: top - size, w: widest, h: lines.length * step };
  const ink = inked(x, top, widest - trailing(spacing), size, lines.length, step);
  const label = claim(text, ink, radar.boxed("HOME"), ratio, prefs);
  return { lines, font, spacing, step, ring, foot, x, last, top, label };
}

function drawHome(radar, ctx, centre, s, ratio, c, prefs, name) {
  const { map } = radar;
  const { lines, step, ring, foot, x, last, top, label } = name;
  ctx.save();
  // Runways in white inside the ring, at their true size.
  if (map && map.runways.length) {
    ctx.strokeStyle = c.white;
    ctx.lineWidth = 1.6 * ratio;
    glow(ctx, c.white, ratio);
    ctx.beginPath();
    for (const [a, b] of map.runways) {
      const p = toScreen(radar, a, s, ctx.canvas.width, ctx.canvas.height);
      const q = toScreen(radar, b, s, ctx.canvas.width, ctx.canvas.height);
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
    }
    ctx.stroke();
  }
  radar.placed.push({ key: "home", ...label });
  // Its box goes down before the ring and the leader, and hides neither;
  // a runway that runs out under the name, it does.
  if (label.box) paintBox(ctx, label.box, c.pink, ratio, prefs);
  ctx.strokeStyle = c.pink;
  ctx.lineWidth = 1.8 * ratio;
  glow(ctx, c.pink, ratio);
  ctx.beginPath();
  ctx.arc(centre[0], centre[1], ring, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.lineWidth = 1.2 * ratio;
  ctx.moveTo(foot[0], foot[1]);
  ctx.lineTo(x - 4 * ratio, last + 6 * ratio);
  ctx.stroke();
  ctx.font = name.font;
  ctx.letterSpacing = `${name.spacing}px`;
  ctx.fillStyle = c.pink;
  ctx.shadowBlur = 0;
  ctx.globalAlpha = radar.hovered === "home" ? 1 : LABEL_ALPHA;
  lines.forEach((line, i) => ctx.fillText(line, x, top + i * step));
  ctx.restore();
}

function nameLines(airport) {
  const name = (airport.name || airport.icao).toUpperCase().replace(/\s+AIRPORT$/, "");
  const words = name.split(/\s+/);
  if (name.length <= 16 || words.length < 2) return [name];
  const half = Math.ceil(words.length / 2);
  return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
}
