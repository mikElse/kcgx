// The static layer (spec, Radar; Rendering): the map, the range rings, the
// home airport and its runways, places and state names. Drawn into an
// offscreen canvas (`radar.still`) once per airport, resize, pan, zoom,
// range, palette, setting or hover change, and copied each frame by
// radar/index.js.
//
// How each part is drawn is a row of the `map` table (prefs.map, phase G
// Task 10): whether it shows, its alpha, its line's pattern and width and
// its label's size. The table's defaults draw what this layer drew before
// the table; a row's alpha scales every part of it from there. Labels
// follow the zoom (`labelPx`), and up close a runway is drawn as wide as it
// is.
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
const FT_PER_NM = 6076.12;
const RING_STEPS_NM = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50];
const RINGS_IN_VIEW = 5; // at most this many between the centre and the nearer edge
const SMALL_AIRPORTS_NM = 27; // small airports show from this view inwards
const HOME_NM = 2.5; // the home ring's true size,
const HOME_MIN_PX = 24; // and what it is held between on screen
const HOME_MAX_PX = 64;
const RING_GAP_PX = 4; // how far a ring's number stands off its ring and clear of the home ring,
const RING_APART_PX = 2; // and of another ring's number
const DRAW_ON_MS = 2000;
const LABEL_ALPHA = 0.4;
const VOR = new Set(["VOR", "VOR-DME", "VORTAC", "TACAN"]);
const SYMBOL_PX = 6; // a place's symbol reaches this far from its point
const MARK_PX = 10; // and a click this near its point is on it
// The label box setting (prefs.box_items) that covers each kind of place.
const BOXED_AS = { navaid: "NAVAIDS", airport: "AIRPORTS", city: "CITIES", peak: "PEAKS" };

const DRAWN_ON = new Set(["coast", "lake", "river", "country", "state"]);
const RUNWAY_FT = 150; // a runway's width where the map has none

// The map's lines, in the order they are drawn: the table's row, the map's
// layer and the palette colour.
const LINES = [
  ["AIRWAY", "airway", "blue"],
  ["STATE", "state", "dim"],
  ["COUNTRY", "country", "green"],
  ["RIVER", "river", "cyan"],
  ["LAKE", "lake", "cyan"],
  ["COAST", "coast", "cyan"],
  ["CLASS_D", "airspace_d", "alarm"],
  ["CLASS_C", "airspace_c", "alarm"],
  ["CLASS_B", "airspace_b", "alarm"],
];
const ROW_OF_LAYER = Object.fromEntries(LINES.map(([row, layer]) => [layer, row]));
// The table's row for each kind of place.
const PLACE_ROW = { navaid: "NAVAIDS", airport: "AIRPORTS", city: "CITIES", peak: "PEAKS" };

// A line's pattern, in units of its width.
const DASHES = { SOLID: [], DASH: [5, 5], DOT: [1, 3] };
// Five layers were dashed before the table, each in a pattern of its own
// that none of those match: an airway's 3 on 6 is no 5w on 5w, and Class
// D's dots were 3 on 5. Each keeps its own as its default line's pattern,
// in px at its default width (tenths) and scaled with the width from there,
// so the default table draws what was drawn. Its other lines are as above.
const OWN_DASH = {
  AIRWAY: ["DASH", [3, 6], 12],
  COUNTRY: ["DASH", [6, 4], 12],
  CLASS_B: ["DASH", [5, 5], 14],
  CLASS_C: ["DASH", [5, 5], 13],
  CLASS_D: ["DOT", [3, 5], 10],
};

function dashOf(row, line, width, ratio) {
  const own = OWN_DASH[row];
  if (own && own[0] === line) return own[1].map((n) => (n * width * ratio) / own[2]);
  return DASHES[line].map((n) => (n * width * ratio) / 10);
}

// The alpha a row's parts were drawn at before the table had them, which
// its default is: the row's alpha scales each part from what it was then
// (a ring at 0.35 and the range at 0.8; a place's symbol at 0.85 and its
// label at LABEL_ALPHA). A row not here was drawn at 100.
const ALPHA_WAS = { RINGS: 35, AIRPORTS: 85, NAVAIDS: 85, CITIES: 85, PEAKS: 85 };

// How a label's size follows the zoom (phase G decision 13).
const LABEL_GROWTH = 0.35;

// A label's text height in CSS px for a row's size `base`, which is its
// size at the view the range sets: zoomed in by k it is `base * k^0.35`,
// zoomed out by k divided by that, held between prefs.label_min and
// label_max. A base outside the two widens them to take it in, so the view
// the range sets always shows a label at its own size (the home airport's
// 30 px name is over the 26 px ceiling). The tags take theirs from
// prefs.tag_px the same way.
export function labelPx(base, radar) {
  const { label_min: low, label_max: high } = radar.store.state.prefs;
  const grown = base * (radar.range() / radar.view.nm) ** LABEL_GROWTH;
  return Math.min(Math.max(grown, Math.min(low, base)), Math.max(high, base));
}

// A row of the table as it is drawn, in canvas px: { show, alpha, dash,
// width, label }, with only the keys the row has. `strength` is what its
// parts' old alphas are multiplied by.
function look(radar, row, ratio) {
  const cells = radar.store.state.prefs.map[row];
  const out = { show: cells.show, alpha: cells.alpha / 100 };
  if ("line" in cells) out.dash = dashOf(row, cells.line, cells.width, ratio);
  if ("width" in cells) out.width = (cells.width * ratio) / 10;
  if ("label" in cells) out.label = labelPx(cells.label, radar) * ratio;
  Object.defineProperty(out, "strength", { value: cells.alpha / (ALPHA_WAS[row] || 100) });
  return out;
}

// An alpha a part was drawn at, scaled by its row.
const part = (style, was) => Math.min(1, was * style.strength);

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
  // `point` is its place's own point on the screen, `xy` the same in nm:
  // what a click on the label centres (phase G Task 12).
  radar.placed = []; // [{ key, ...label, point: [x, y], xy: [x, y] }]
  // Every symbol drawn, labelled or not, and the home ring: what a click
  // within `reach` px of its point centres.
  radar.marks = []; // [{ key, point: [x, y], xy: [x, y] in nm, reach }], as last drawn
  radar.rings = []; // [{ nm, r, bright, text, label: {...label, at: [x, baseline]} or null }], as last drawn
  radar.home = { x: 0, y: 0, r: 0 }; // the airport and its ring, as last drawn
  radar.symbols = {}; // kind -> how many are on screen, as last drawn
  radar.styles = {}; // row -> its look() and, for RUNWAYS, what was drawn, as last drawn
  radar.layers = {}; // the map's layer -> how many pieces it has, 0 while its row is hidden, as last drawn
  radar.blurMap = 0; // the map's glow in canvas px, as last drawn
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
        placed: [...radar.placed], marks: [...radar.marks], hovered: radar.hovered, mapFor: radar.mapFor, loaded: Boolean(map),
        rings: [...radar.rings], home: { ...radar.home }, symbols: { ...radar.symbols },
        layers: { ...radar.layers }, styles: JSON.parse(JSON.stringify(radar.styles)), blur_map: radar.blurMap,
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

// A line piece is its points in nm, [x0, y0, x1, y1, ...], with `box`, the
// least rectangle that holds them: [minx, miny, maxx, maxy].
function decode(geo, project) {
  const q = geo.q;
  const lines = {};
  for (const [layer, pieces] of Object.entries(geo.lines)) {
    lines[layer] = pieces.map((piece) => {
      const out = new Float32Array(piece.length);
      const box = [Infinity, Infinity, -Infinity, -Infinity];
      let x = piece[0];
      let y = piece[1];
      for (let i = 0; i < piece.length; i += 2) {
        if (i) { x += piece[i]; y += piece[i + 1]; }
        const [px, py] = project(y / q, x / q);
        out[i] = px;
        out[i + 1] = py;
        box[0] = Math.min(box[0], px); box[1] = Math.min(box[1], py);
        box[2] = Math.max(box[2], px); box[3] = Math.max(box[3], py);
      }
      out.box = box;
      return out;
    });
  }
  const at = (row) => project(row[1] / q, row[0] / q);
  const points = {};
  for (const [kind, rows] of Object.entries(geo.points)) points[kind] = rows.map((row) => ({ xy: at(row), row }));
  const labels = {};
  for (const [kind, rows] of Object.entries(geo.labels)) labels[kind] = rows.map((row) => ({ xy: at(row), row }));
  // [x1, y1, x2, y2] and, where the map has it, the width in feet.
  const runways = geo.runways.map((r) => ({
    ends: [project(r[1] / q, r[0] / q), project(r[3] / q, r[2] / q)],
    ft: r[4] || RUNWAY_FT,
  }));
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
// the airport's name, boxed or bare (the owner's decision in phase G: phase
// F let a bare number and the name cross, as places still may). null when
// neither has room, or when the number would touch one of `numbered`,
// those already placed. A boxed number needs the room for its box.
function ringLabel(radar, ctx, ring, centre, width, height, ratio, clear, numbered, name, h) {
  const w = ctx.measureText(ring.text).width;
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

// The part of the segment from (x0, y0) to (x0 + dx, y0 + dy) inside the
// rectangle [left, right] x [top, bottom], as the share of the way along it
// that the part starts and ends: [t0, t1], or null when none is inside
// (Liang and Barsky).
function clip(x0, y0, dx, dy, left, top, right, bottom) {
  let t0 = 0;
  let t1 = 1;
  for (const [p, q] of [[-dx, x0 - left], [dx, right - x0], [-dy, y0 - top], [dy, bottom - y0]]) {
    if (p === 0) {
      if (q < 0) return null;
    } else {
      const r = q / p;
      if (p < 0) { if (r > t1) return null; if (r > t0) t0 = r; } else { if (r < t0) return null; if (r < t1) t1 = r; }
    }
  }
  return [t0, t1];
}

// The lines as they cross the screen and `margin` px about it, which no
// line or glow reaches past: each segment is cut to that rectangle and the
// rest left out. Up close one segment runs tens of thousands of px off the
// screen, and a dashed path that long is drawn solid (Skia gives up on
// dashing past a count) as well as slowly. A line that comes back onto the
// screen starts a new subpath, whose dashes would start afresh: it starts
// instead the dash's phase back along its way, outside the rectangle, so
// its dashes fall where they would have along the whole line. `period` is
// the dash pattern's length in px, 0 for a solid line.
function strokeLines(radar, ctx, lines, s, width, height, progress, margin, period) {
  ctx.beginPath();
  const ox = width / 2 - radar.view.panX * s;
  const oy = height / 2 - radar.view.panY * s;
  const [left, top, right, bottom] = [-margin, -margin, width + margin, height + margin];
  const [boxLeft, boxTop] = [(left - ox) / s, (top - oy) / s];
  const [boxRight, boxBottom] = [(right - ox) / s, (bottom - oy) / s];
  for (const line of lines) {
    const [x0, y0, x1, y1] = line.box;
    if (x1 < boxLeft || x0 > boxRight || y1 < boxTop || y0 > boxBottom) continue;
    const n = line.length / 2;
    const upto = progress >= 1 ? n : Math.max(2, Math.ceil(n * progress));
    let along = 0; // px from the piece's start to this segment's
    let pen = false; // whether the subpath runs up to this segment's start
    let ax = ox + line[0] * s;
    let ay = oy + line[1] * s;
    for (let i = 1; i < upto; i += 1) {
      const bx = ox + line[2 * i] * s;
      const by = oy + line[2 * i + 1] * s;
      const dx = bx - ax;
      const dy = by - ay;
      const length = Math.hypot(dx, dy);
      const inside = clip(ax, ay, dx, dy, left, top, right, bottom);
      if (!inside) {
        pen = false;
      } else {
        const [t0, t1] = inside;
        if (!pen || t0 > 0) {
          const sx = ax + dx * t0;
          const sy = ay + dy * t0;
          const back = period && length ? (along + t0 * length) % period : 0;
          if (back) {
            ctx.moveTo(sx - (dx / length) * back, sy - (dy / length) * back);
            ctx.lineTo(sx, sy);
          } else {
            ctx.moveTo(sx, sy);
          }
        }
        ctx.lineTo(ax + dx * t1, ay + dy * t1);
        pen = t1 === 1;
      }
      along += length;
      ax = bx;
      ay = by;
    }
  }
  ctx.stroke();
}

function glow(ctx, colour, ratio) {
  ctx.shadowColor = colour;
  ctx.shadowBlur = glowBlur("map") * ratio;
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
  const styles = radar.styles;
  for (const row of Object.keys(styles)) delete styles[row];
  for (const row of Object.keys(prefs.map)) styles[row] = look(radar, row, ratio);
  for (const layer of Object.keys(radar.layers)) delete radar.layers[layer];
  radar.blurMap = glowBlur("map") * ratio;

  if (map) {
    for (const [layer, lines] of Object.entries(map.lines)) {
      const row = ROW_OF_LAYER[layer];
      radar.layers[layer] = row && !styles[row].show ? 0 : lines.length;
    }
    for (const [row, layer, colour] of LINES) {
      const lines = map.lines[layer];
      const style = styles[row];
      if (!style.show || !lines || !lines.length) continue;
      ctx.save();
      ctx.globalAlpha = style.alpha;
      ctx.strokeStyle = c[colour];
      ctx.lineWidth = style.width;
      ctx.setLineDash(style.dash);
      glow(ctx, c[colour], ratio);
      const margin = style.width + 3 * radar.blurMap; // past which neither a line nor its glow reaches the screen
      const period = style.dash.reduce((a, b) => a + b, 0) * (style.dash.length % 2 ? 2 : 1);
      strokeLines(radar, ctx, lines, s, width, height, DRAWN_ON.has(layer) ? progress : 1, margin, period);
      ctx.restore();
    }
  }

  // Range rings, dim, and the range itself, bright. Each is numbered where
  // there is room; the range's number is placed first, so a dim ring's
  // that would touch it is the one left off. The airport's name has its
  // place before any of them, and no number is drawn across it.
  const { rings } = radar;
  const ringStyle = styles.RINGS;
  rings.splice(0, rings.length, ...(ringStyle.show ? ringsOn(radar, centre, s, width, height) : []));
  const name = styles.HOME.show ? homeName(radar, ctx, centre, s, ratio, prefs) : null;
  const keepOff = name ? name.label : null;
  ctx.save();
  ctx.strokeStyle = c.cyan;
  ctx.lineWidth = ringStyle.width;
  ctx.setLineDash(ringStyle.dash);
  glow(ctx, c.cyan, ratio);
  for (const ring of rings) {
    ctx.globalAlpha = part(ringStyle, ring.bright ? 0.8 : 0.35);
    ctx.beginPath();
    ctx.arc(centre[0], centre[1], ring.r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
  ctx.save();
  ctx.fillStyle = c.dim;
  ctx.globalAlpha = part(ringStyle, 1);
  ctx.font = `${ringStyle.label}px ${FONT}`;
  const clear = homeRing(s, ratio) + RING_GAP_PX * ratio;
  const numbered = [];
  for (const ring of [...rings.filter((r) => r.bright), ...rings.filter((r) => !r.bright)]) {
    ring.label = ringLabel(radar, ctx, ring, centre, width, height, ratio, clear, numbered, keepOff, ringStyle.label);
    if (!ring.label) continue;
    numbered.push(ring.label);
    if (ring.label.box) paintBox(ctx, ring.label.box, c.dim, ratio, prefs);
    ctx.fillText(ring.text, ring.label.at[0], ring.label.at[1]);
  }
  ctx.restore();

  // The runways, then the home airport, so its name is reserved before
  // any place looks for room.
  radar.placed.length = 0;
  radar.marks.length = 0;
  for (const kind of Object.keys(radar.symbols)) delete radar.symbols[kind];
  Object.assign(radar.home, { x: centre[0], y: centre[1], r: homeRing(s, ratio) });
  styles.RUNWAYS.drawn = map && styles.RUNWAYS.show ? drawRunways(radar, ctx, s, width, height, ratio, c, styles.RUNWAYS) : [];
  if (name) drawHome(radar, ctx, centre, ratio, c, prefs, name, styles.HOME);
  if (map) drawPlaces(radar, ctx, s, width, height, ratio, c, prefs, styles);
  radar.staticDirty = progress < 1;
}

// Runways in white about the airport, each as long as it is. Far out, a
// line the row's width; once a runway's true width is wider than that, a
// filled quadrilateral that wide. Returns what was drawn, for tests:
// [{ ends: [[x, y], [x, y]], ft, px, filled }].
function drawRunways(radar, ctx, s, width, height, ratio, c, style) {
  const drawn = [];
  const quads = [];
  ctx.save();
  ctx.globalAlpha = style.alpha;
  ctx.strokeStyle = c.white;
  ctx.fillStyle = c.white;
  ctx.lineWidth = style.width;
  glow(ctx, c.white, ratio);
  ctx.beginPath();
  for (const { ends: [a, b], ft } of radar.map.runways) {
    const p = toScreen(radar, a, s, width, height);
    const q = toScreen(radar, b, s, width, height);
    const wide = (ft / FT_PER_NM) * s;
    const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
    const filled = wide > style.width && length > 0;
    drawn.push({ ends: [p, q], ft, px: Math.max(style.width, wide), filled });
    if (filled) {
      quads.push([p, q, (-(q[1] - p[1]) / length) * (wide / 2), ((q[0] - p[0]) / length) * (wide / 2)]);
    } else {
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
    }
  }
  ctx.stroke();
  if (quads.length) {
    ctx.beginPath();
    for (const [p, q, nx, ny] of quads) {
      ctx.moveTo(p[0] + nx, p[1] + ny);
      ctx.lineTo(q[0] + nx, q[1] + ny);
      ctx.lineTo(q[0] - nx, q[1] - ny);
      ctx.lineTo(p[0] - nx, p[1] - ny);
      ctx.closePath();
    }
    ctx.fill();
  }
  ctx.restore();
  return drawn;
}

// Symbols and labels, placed greedily by priority so no two labels
// overlap; a label that does not fit is left off, its symbol stays. Every
// label is given its place before anything is drawn, so that the boxes can
// go down first: a box hides the map under it, never a symbol or a name.
function drawPlaces(radar, ctx, s, width, height, ratio, c, prefs, styles) {
  const { map, placed, symbols, rings } = radar;
  const boxed = radar.boxed;
  const onScreen = ([x, y]) => x > -40 && y > -40 && x < width + 40 && y < height + 40;
  const shows = (kind) => styles[PLACE_ROW[kind]].show;
  const items = [];
  for (const { xy, row } of shows("navaid") ? map.points.navaid || [] : []) {
    if (!VOR.has(row[3])) continue;
    items.push({ kind: "navaid", xy, text: row[2], colour: c.cyan, priority: 30 });
  }
  for (const { xy, row } of shows("airport") ? map.points.airport || [] : []) {
    if (row[3] === "small" && radar.view.nm > SMALL_AIRPORTS_NM) continue;
    items.push({ kind: "airport", xy, text: row[2], colour: c.cyan, priority: row[3] === "large" ? 25 : row[3] === "medium" ? 35 : 60 });
  }
  for (const { xy, row } of shows("city") ? map.points.city || [] : []) {
    items.push({ kind: "city", xy, text: row[2], colour: c.amber, priority: row[3] });
  }
  for (const { xy, row } of shows("peak") ? map.points.peak || [] : []) {
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
  // The label's place if there is room for it, which is then taken. `p`
  // is its place's point on the screen and `xy` in nm.
  const place = (key, label, p, xy) => {
    if (!free(label)) return null;
    taken.push(label);
    placed.push({ key, ...label, point: p, xy });
    return label;
  };

  ctx.save();
  // A kind of place's text height is its row's; the state names' spacing
  // and their place about their point grow with theirs.
  let font = "";
  const placeFont = (kind) => {
    const want = `${styles[PLACE_ROW[kind]].label}px ${FONT}`;
    if (want !== font) { ctx.font = want; font = want; }
  };
  const statePx = styles.STATE_NAMES.label;
  const stateEm = statePx / (14 * ratio);
  const stateFont = () => { ctx.font = `${statePx}px ${FONT}`; font = ""; ctx.letterSpacing = `${6 * ratio * stateEm}px`; };
  const placeSpacing = () => { ctx.letterSpacing = `${1.5 * ratio}px`; };

  placeSpacing();
  const places = []; // [{ item, p, key, baseline, label or null }]
  const reach = SYMBOL_PX * ratio;
  for (const item of items) {
    const p = toScreen(radar, item.xy, s, width, height);
    if (!onScreen(p)) continue;
    // Airports within the home ring are the home airport itself.
    if (item.kind === "airport" && Math.hypot(p[0] - home[0], p[1] - home[1]) < 8 * ratio) continue;
    symbols[item.kind] = (symbols[item.kind] || 0) + 1;
    placeFont(item.kind);
    const w = ctx.measureText(item.text).width;
    const h = styles[PLACE_ROW[item.kind]].label;
    const text = { x: p[0] + 8 * ratio, y: p[1] - h / 2 - 2 * ratio, w, h: h + 4 * ratio };
    const baseline = p[1] + h / 2 - 2 * ratio;
    // A place's box takes in its symbol: the two are one thing.
    const ink = around(
      inked(text.x, baseline, w - trailing(1.5 * ratio), h),
      { x: p[0] - reach, y: p[1] - reach, w: 2 * reach, h: 2 * reach },
    );
    const key = `${item.kind}:${item.text}`;
    radar.marks.push({ key, point: p, xy: item.xy, reach: MARK_PX * ratio });
    const label = place(key, claim(text, ink, boxed(BOXED_AS[item.kind]), ratio, prefs), p, item.xy);
    places.push({ item, p, key, baseline, label });
  }

  // State names: large, spaced, dim, and the first thing given up.
  stateFont();
  const states = []; // [{ name, key, x, baseline, label }]
  for (const { xy, row } of styles.STATE_NAMES.show ? map.labels.state || [] : []) {
    const p = toScreen(radar, xy, s, width, height);
    if (!onScreen(p)) continue;
    const w = ctx.measureText(row[2]).width;
    const text = { x: p[0] - w / 2, y: p[1] - 10 * ratio * stateEm, w, h: 18 * ratio * stateEm };
    const baseline = p[1] + 5 * ratio * stateEm;
    const ink = inked(text.x, baseline, w - trailing(6 * ratio * stateEm), statePx);
    const key = `state:${row[2]}`;
    const label = place(key, claim(text, ink, boxed("STATES"), ratio, prefs), p, xy);
    if (label) states.push({ name: row[2], key, x: text.x, baseline, label });
  }

  // A box keeps its strength while its label brightens under the pointer.
  for (const { item, label } of places) if (label && label.box) paintBox(ctx, label.box, item.colour, ratio, prefs);
  for (const { label } of states) if (label.box) paintBox(ctx, label.box, c.dim, ratio, prefs);

  placeSpacing();
  for (const { item, p, key, baseline, label } of places) {
    const style = styles[PLACE_ROW[item.kind]];
    ctx.globalAlpha = part(style, 0.85);
    ctx.strokeStyle = item.colour;
    ctx.lineWidth = style.width;
    glow(ctx, item.colour, ratio);
    symbol(ctx, item.kind, p, ratio);
    if (!label) continue;
    ctx.shadowBlur = 0;
    ctx.globalAlpha = part(style, radar.hovered === key ? 1 : LABEL_ALPHA);
    ctx.fillStyle = item.colour;
    placeFont(item.kind);
    ctx.fillText(item.text, p[0] + 8 * ratio, baseline);
  }

  stateFont();
  ctx.shadowBlur = 0;
  ctx.fillStyle = c.dim;
  for (const { name, key, x, baseline } of states) {
    ctx.globalAlpha = part(styles.STATE_NAMES, radar.hovered === key ? 1 : LABEL_ALPHA);
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
  const size = radar.styles.HOME.label;
  const step = size + 2 * ratio;
  const foot = [centre[0] + ring * 0.7, centre[1] - ring * 0.7];
  const x = foot[0] + 12 * ratio;
  const last = foot[1] - 14 * ratio; // the bottom line's baseline
  const top = last - (lines.length - 1) * step;
  const font = `${size}px ${FONT}`;
  const spacing = (3 * size) / 30;
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

function drawHome(radar, ctx, centre, ratio, c, prefs, name, style) {
  const { lines, step, ring, foot, x, last, top, label } = name;
  ctx.save();
  radar.placed.push({ key: "home", ...label, point: [...centre], xy: [0, 0] });
  radar.marks.push({ key: "home", point: [...centre], xy: [0, 0], reach: ring });
  // Its box goes down before the ring and the leader, and hides neither;
  // a runway that runs out under the name, it does.
  if (label.box) paintBox(ctx, label.box, c.pink, ratio, prefs);
  ctx.globalAlpha = part(style, 1);
  ctx.strokeStyle = c.pink;
  ctx.lineWidth = style.width;
  glow(ctx, c.pink, ratio);
  ctx.beginPath();
  ctx.arc(centre[0], centre[1], ring, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.lineWidth = (style.width * 1.2) / 1.8; // the leader, a little finer than the ring
  ctx.moveTo(foot[0], foot[1]);
  ctx.lineTo(x - 4 * ratio, last + 6 * ratio);
  ctx.stroke();
  ctx.font = name.font;
  ctx.letterSpacing = `${name.spacing}px`;
  ctx.fillStyle = c.pink;
  ctx.shadowBlur = 0;
  ctx.globalAlpha = part(style, radar.hovered === "home" ? 1 : LABEL_ALPHA);
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
