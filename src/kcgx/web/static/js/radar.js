// The radar (spec, Radar; Visual language; Rendering). Our own vector
// renderer on one canvas: an azimuthal equidistant projection centred on
// the airport, so range rings are true circles and distance reads straight
// off the screen.
//
// Two layers. The static one (map, rings, labels, the home airport) is
// drawn into an offscreen canvas once per airport, resize, pan, zoom,
// range, palette or hover change, and copied each frame. The moving one
// (aircraft, trails, the focus ring) is drawn every frame, dead reckoned
// between polls from ground speed and track. With display VECTOR or CRT
// the moving layer fades instead of clearing, which is the phosphor
// persistence.

import { colours, glowBlur, reducedMotion } from "./theme.js";
import { focus } from "./focus.js";

const NM_PER_RADIAN = 3440.065;
const VIEW_MIN_NM = 2.5; // the closest view: this far from the centre to the nearer edge
const VIEW_MAX_NM = 160; // the widest, or the range if that is wider
const RING_STEPS_NM = [0.5, 1, 2, 5, 10, 20, 50];
const RINGS_IN_VIEW = 5; // at most this many between the centre and the nearer edge
const SMALL_AIRPORTS_NM = 27; // small airports show from this view inwards
const HOME_NM = 2.5; // the home ring's true size,
const HOME_MIN_PX = 24; // and what it is held between on screen
const HOME_MAX_PX = 64;
const EDGE_PX = 18; // kept clear between the view's distance and the nearer edge
const RING_TEXT_PX = 12; // a ring's number,
const RING_GAP_PX = 4; // how far it stands off its ring and clear of the home ring,
const RING_APART_PX = 2; // and of another ring's number
const DRAW_ON_MS = 2000;
const LABEL_ALPHA = 0.4;
const DIM_ALPHA = 0.15;
const STALE_FADE_FROM = 30; // seconds without a position before an aircraft fades
const EMERGENCY = new Set(["7500", "7600", "7700"]);
const VOR = new Set(["VOR", "VOR-DME", "VORTAC", "TACAN"]);
const FONT = '"Share Tech Mono", monospace';

const DRAWN_ON = new Set(["coast", "lake", "river", "country", "state"]);

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

// Where an aircraft will be `seconds` after its last position.
export function reckon(lat, lon, gs, trk, seconds) {
  if (!gs || trk === null || trk === undefined || seconds <= 0) return [lat, lon];
  const nm = (gs * seconds) / 3600;
  const b = (trk * Math.PI) / 180;
  const dlat = (nm * Math.cos(b)) / 60;
  const dlon = (nm * Math.sin(b)) / (60 * Math.max(0.01, Math.cos((lat * Math.PI) / 180)));
  return [lat + dlat, lon + dlon];
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

// -- the screen ------------------------------------------------------------------

export function mountRadar(canvas, store, { hud = {} } = {}) {
  // The range is a setting (prefs.range_nm). The view is held in nautical
  // miles: `nm` from the centre to the nearer edge, less EDGE_PX. It starts
  // at the range and returns to it; pan is in nm too.
  const range = () => store.state.prefs.range_nm;
  const view = { nm: range(), panX: 0, panY: 0 };
  let viewFor = view.nm; // the range the view was last reset for
  let map = null; // decoded geo for the current airport
  let mapFor = "";
  let project = null;
  let drawOnFrom = 0;
  let staticDirty = true;
  let hovered = null; // a placed label's key
  let placed = []; // [{ key, x, y, w, h }]
  let rings = []; // [{ nm, r, bright, text, label: {x, y, w, h} or null }], as last drawn
  let home = { x: 0, y: 0, r: 0 }; // the airport and its ring, as last drawn
  let symbols = {}; // kind -> how many are on screen, as last drawn
  let shown = null; // the view and the range, as the last frame drew them
  let hits = []; // [{ hex, x, y, label: {x, y, w, h}, trail: [[x, y]] }]
  // moved: the press now down, or the last one, became a drag. before: the
  // press ahead of it did. at: where the pointer last was.
  const pointer = { down: null, moved: false, before: false, at: [0, 0] };
  const still = document.createElement("canvas");
  const trace = document.createElement("canvas"); // the moving layer, for persistence

  // -- sizes and the transform --

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    for (const c of [canvas, still, trace]) {
      if (c.width !== width || c.height !== height) { c.width = width; c.height = height; staticDirty = true; }
    }
    return { ratio, width, height };
  }

  // Pixels per nm: the view's distance fits the shorter side.
  function scale(width, height, ratio) {
    return Math.max(0, Math.min(width, height) / 2 - EDGE_PX * ratio) / view.nm;
  }

  // Back to the whole range, about the airport. A drag that is under way
  // (the range or the airport can change beneath one) carries on from here.
  function recentre() {
    view.nm = range();
    view.panX = 0;
    view.panY = 0;
    viewFor = view.nm;
    if (pointer.down) pointer.down = { at: pointer.at, panX: 0, panY: 0 };
    staticDirty = true;
  }

  // The home ring is 2.5 nm, held between two sizes on screen so that it
  // neither vanishes at a wide view nor fills a close one.
  function homeRing(s, ratio) {
    return Math.min(HOME_MAX_PX * ratio, Math.max(HOME_MIN_PX * ratio, HOME_NM * s));
  }

  // Which rings cross the screen: every multiple of a 1, 2, 5 step short of
  // the range, and the range itself whether or not it is a multiple. The
  // step is the smallest that puts no more than five between the centre and
  // the nearer edge.
  function ringsOn(centre, s, width, height) {
    if (s <= 0) return [];
    const dx = Math.max(0, -centre[0], centre[0] - width);
    const dy = Math.max(0, -centre[1], centre[1] - height);
    const nearest = Math.hypot(dx, dy) / s; // nm from the airport to the screen
    const farthest = Math.hypot(
      Math.max(centre[0], width - centre[0]), Math.max(centre[1], height - centre[1]),
    ) / s;
    const limit = range();
    const step = RING_STEPS_NM.find((nm) => view.nm / nm <= RINGS_IN_VIEW) || RING_STEPS_NM[RING_STEPS_NM.length - 1];
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
  // to the other when it is off the screen or on the home ring. null when
  // neither has room, or when the number would touch one of `numbered`,
  // those already placed.
  function ringLabel(ctx, ring, centre, width, height, ratio, clear, numbered) {
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
      const box = { x: ux >= 0 ? x + gap : x - gap - w, y: uy <= 0 ? y - gap - h : y + gap, w, h };
      if (box.x < 0 || box.y < 0 || box.x + w > width || box.y + h > height) continue;
      const nearX = Math.max(box.x - centre[0], 0, centre[0] - box.x - w);
      const nearY = Math.max(box.y - centre[1], 0, centre[1] - box.y - h);
      if (Math.hypot(nearX, nearY) < clear) continue;
      const touches = numbered.some((n) => (
        box.x < n.x + n.w + apart && n.x < box.x + w + apart && box.y < n.y + n.h + apart && n.y < box.y + h + apart
      ));
      return touches ? null : box;
    }
    return null;
  }

  function toScreen(xy, s, width, height) {
    return [width / 2 + (xy[0] - view.panX) * s, height / 2 + (xy[1] - view.panY) * s];
  }

  // -- the map --

  async function loadMap(airport) {
    const key = airport.icao;
    mapFor = key;
    map = null;
    project = airport.lat === null ? null : projector(airport.lat, airport.lon);
    staticDirty = true;
    if (!project) return;
    try {
      const response = await fetch(`/api/geo?icao=${encodeURIComponent(key)}`);
      if (!response.ok) throw new Error(`${response.status}`);
      const geo = await response.json();
      if (mapFor !== key) return; // the airport changed while we were asking
      map = decode(geo, project);
      drawOnFrom = reducedMotion() ? 0 : performance.now();
      staticDirty = true;
    } catch {
      map = null;
    }
  }

  function strokeLines(ctx, lines, s, width, height, progress) {
    ctx.beginPath();
    const ox = width / 2 - view.panX * s;
    const oy = height / 2 - view.panY * s;
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

  function drawStatic(now) {
    const { ratio, width, height } = size();
    const ctx = still.getContext("2d");
    const c = colours();
    const s = scale(width, height, ratio);
    const centre = toScreen([0, 0], s, width, height);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.globalCompositeOperation = "lighter";
    const progress = drawOnFrom ? Math.min(1, (now - drawOnFrom) / DRAW_ON_MS) : 1;

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
        strokeLines(ctx, lines, s, width, height, DRAWN_ON.has(layer) ? progress : 1);
        ctx.restore();
      }
    }

    // Range rings, dim, and the range itself, bright. Each is numbered where
    // there is room; the range's number is placed first, so a dim ring's
    // that would touch it is the one left off.
    rings = ringsOn(centre, s, width, height);
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
      ring.label = ringLabel(ctx, ring, centre, width, height, ratio, clear, numbered);
      if (!ring.label) continue;
      numbered.push(ring.label);
      ctx.fillText(ring.text, ring.label.x, ring.label.y + ring.label.h);
    }
    ctx.restore();

    // The home airport first, so its name is reserved before anything else
    // looks for room.
    placed = [];
    symbols = {};
    home = { x: centre[0], y: centre[1], r: homeRing(s, ratio) };
    drawHome(ctx, centre, s, ratio, c);
    if (map) drawPlaces(ctx, s, width, height, ratio, c);
    staticDirty = progress < 1;
  }

  // Symbols and labels, placed greedily by priority so no two labels
  // overlap; a label that does not fit is left off, its symbol stays.
  function drawPlaces(ctx, s, width, height, ratio, c) {
    const onScreen = ([x, y]) => x > -40 && y > -40 && x < width + 40 && y < height + 40;
    const items = [];
    for (const { xy, row } of map.points.navaid || []) {
      if (!VOR.has(row[3])) continue;
      items.push({ kind: "navaid", xy, text: row[2], colour: c.cyan, priority: 30 });
    }
    for (const { xy, row } of map.points.airport || []) {
      if (row[3] === "small" && view.nm > SMALL_AIRPORTS_NM) continue;
      items.push({ kind: "airport", xy, text: row[2], colour: c.cyan, priority: row[3] === "large" ? 25 : row[3] === "medium" ? 35 : 60 });
    }
    for (const { xy, row } of map.points.city || []) {
      items.push({ kind: "city", xy, text: row[2], colour: c.amber, priority: row[3] });
    }
    for (const { xy, row } of map.points.peak || []) {
      items.push({ kind: "peak", xy, text: row[2], colour: c.amber, priority: 20 });
    }
    items.sort((a, b) => a.priority - b.priority);

    // The home airport's own name and ring are reserved first.
    const home = toScreen([0, 0], s, width, height);
    const clear = homeRing(s, ratio) + 2 * ratio;
    const taken = [{ x: home[0] - clear, y: home[1] - clear, w: 2 * clear, h: 2 * clear }, ...placed];
    const free = (r) => taken.every((t) => r.x + r.w < t.x || t.x + t.w < r.x || r.y + r.h < t.y || t.y + t.h < r.y);

    ctx.save();
    ctx.lineWidth = 1.3 * ratio;
    ctx.font = `${13 * ratio}px ${FONT}`;
    ctx.letterSpacing = `${1.5 * ratio}px`;
    for (const item of items) {
      const p = toScreen(item.xy, s, width, height);
      if (!onScreen(p)) continue;
      // Airports within the home ring are the home airport itself.
      if (item.kind === "airport" && Math.hypot(p[0] - home[0], p[1] - home[1]) < 8 * ratio) continue;
      ctx.globalAlpha = 0.85;
      ctx.strokeStyle = item.colour;
      glow(ctx, item.colour, ratio);
      symbol(ctx, item.kind, p, ratio);
      symbols[item.kind] = (symbols[item.kind] || 0) + 1;
      const w = ctx.measureText(item.text).width;
      const h = 13 * ratio;
      const box = { x: p[0] + 8 * ratio, y: p[1] - h / 2 - 2 * ratio, w, h: h + 4 * ratio };
      if (!free(box)) continue;
      taken.push(box);
      const key = `${item.kind}:${item.text}`;
      placed.push({ key, ...box });
      ctx.shadowBlur = 0;
      ctx.globalAlpha = hovered === key ? 1 : LABEL_ALPHA;
      ctx.fillStyle = item.colour;
      ctx.fillText(item.text, box.x, p[1] + h / 2 - 2 * ratio);
    }

    // State names: large, spaced, dim, and the first thing given up.
    ctx.font = `${14 * ratio}px ${FONT}`;
    ctx.letterSpacing = `${6 * ratio}px`;
    ctx.fillStyle = c.dim;
    for (const { xy, row } of map.labels.state || []) {
      const p = toScreen(xy, s, width, height);
      if (!onScreen(p)) continue;
      const w = ctx.measureText(row[2]).width;
      const box = { x: p[0] - w / 2, y: p[1] - 10 * ratio, w, h: 18 * ratio };
      if (!free(box)) continue;
      taken.push(box);
      const key = `state:${row[2]}`;
      placed.push({ key, ...box });
      ctx.globalAlpha = hovered === key ? 1 : LABEL_ALPHA;
      ctx.fillText(row[2], box.x, p[1] + 5 * ratio);
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

  function drawHome(ctx, centre, s, ratio, c) {
    const airport = store.state.airport;
    if (!airport) return;
    ctx.save();
    // Runways in white inside the ring, at their true size.
    if (map && map.runways.length) {
      ctx.strokeStyle = c.white;
      ctx.lineWidth = 1.6 * ratio;
      glow(ctx, c.white, ratio);
      ctx.beginPath();
      for (const [a, b] of map.runways) {
        const p = toScreen(a, s, ctx.canvas.width, ctx.canvas.height);
        const q = toScreen(b, s, ctx.canvas.width, ctx.canvas.height);
        ctx.moveTo(p[0], p[1]);
        ctx.lineTo(q[0], q[1]);
      }
      ctx.stroke();
    }
    ctx.strokeStyle = c.pink;
    ctx.lineWidth = 1.8 * ratio;
    glow(ctx, c.pink, ratio);
    const ring = homeRing(s, ratio);
    ctx.beginPath();
    ctx.arc(centre[0], centre[1], ring, 0, Math.PI * 2);
    ctx.stroke();
    // The name, large, above and right of the ring on a short leader, as
    // the film labels its bases.
    const lines = nameLines(airport);
    const size = 30 * ratio;
    const step = size + 2 * ratio;
    const foot = [centre[0] + ring * 0.7, centre[1] - ring * 0.7];
    const x = foot[0] + 12 * ratio;
    const last = foot[1] - 14 * ratio; // the bottom line's baseline
    const top = last - (lines.length - 1) * step;
    ctx.beginPath();
    ctx.lineWidth = 1.2 * ratio;
    ctx.moveTo(foot[0], foot[1]);
    ctx.lineTo(x - 4 * ratio, last + 6 * ratio);
    ctx.stroke();
    ctx.font = `${size}px ${FONT}`;
    ctx.letterSpacing = `${3 * ratio}px`;
    ctx.fillStyle = c.pink;
    ctx.shadowBlur = 0;
    let widest = 0;
    for (const line of lines) widest = Math.max(widest, ctx.measureText(line).width);
    const box = { x, y: top - size, w: widest, h: lines.length * step };
    placed.push({ key: "home", ...box });
    ctx.globalAlpha = hovered === "home" ? 1 : LABEL_ALPHA;
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

  // -- aircraft --

  function aircraftNow() {
    const frame = store.state.radar;
    if (!frame || !project) return [];
    const since = (performance.now() - store.state.radarAt) / 1000;
    return frame.ac.map((ac) => {
      const age = ac.age + since;
      const [lat, lon] = reckon(ac.lat, ac.lon, ac.gs, ac.trk, age);
      return { ...ac, now: project(lat, lon), age };
    });
  }

  function drawMoving(ctx, width, height, ratio, s, c) {
    hits = [];
    const focused = focus.hex;
    const list = aircraftNow();
    if (focused && !list.some((ac) => ac.hex === focused)) focus.set(null);
    for (const ac of list) {
      const emergency = EMERGENCY.has(ac.sq);
      const isFocus = ac.hex === focused;
      const colour = isFocus ? c.pink : emergency ? c.alarm : c.cyan;
      const stale = Math.max(0, Math.min(1, (ac.age - STALE_FADE_FROM) / 30));
      let alpha = 1 - 0.7 * stale;
      if (focused && !isFocus) alpha *= DIM_ALPHA;
      const head = toScreen(ac.now, s, width, height);
      const trail = (store.state.trails.get(ac.hex) || [])
        .map((p) => toScreen(project(p.lat, p.lon), s, width, height))
        .reverse();
      const points = [head, ...trail];

      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1.8 * ratio;
      ctx.strokeStyle = colour;
      glow(ctx, colour, ratio);
      // The trail fades from full at the arrow to nothing at its oldest point.
      for (let i = 1; i < points.length; i += 1) {
        ctx.globalAlpha = alpha * 0.95 * (1 - (i - 1) / (points.length - 1));
        ctx.beginPath();
        ctx.moveTo(points[i - 1][0], points[i - 1][1]);
        ctx.lineTo(points[i][0], points[i][1]);
        ctx.stroke();
      }
      ctx.globalAlpha = alpha;
      // The chevron, pointing along track.
      ctx.save();
      ctx.translate(head[0], head[1]);
      ctx.rotate(((ac.trk || 0) * Math.PI) / 180);
      ctx.beginPath();
      const u = ratio;
      ctx.moveTo(0, -9 * u); ctx.lineTo(0, 9 * u);
      ctx.moveTo(-7 * u, 4 * u); ctx.lineTo(0, -9 * u); ctx.lineTo(7 * u, 4 * u);
      ctx.stroke();
      ctx.restore();
      if (isFocus) {
        ctx.lineWidth = 1.4 * ratio;
        ctx.beginPath();
        ctx.arc(head[0], head[1], 16 * ratio, 0, Math.PI * 2);
        ctx.stroke();
      }
      const text = `${ac.label} ${ac.alt === null ? "" : ac.alt}`.trim();
      ctx.font = `${16 * ratio}px ${FONT}`;
      ctx.letterSpacing = `${1.5 * ratio}px`;
      ctx.fillStyle = colour;
      ctx.shadowBlur = 0;
      const w = ctx.measureText(text).width;
      const left = head[0] + 14 * ratio;
      ctx.fillText(text, left, head[1] - 10 * ratio);
      ctx.restore();
      hits.push({ hex: ac.hex, x: head[0], y: head[1], label: { x: left, y: head[1] - 26 * ratio, w, h: 20 * ratio }, trail: points });
    }
    return list;
  }

  // -- the frame loop --

  function persistence() {
    const display = document.documentElement.dataset.display;
    return display !== "OFF" && !reducedMotion();
  }

  let lastHud = 0;
  function frame(now) {
    const { ratio, width, height } = size();
    if (staticDirty) drawStatic(now);
    const c = colours();
    const s = scale(width, height, ratio);

    const t = trace.getContext("2d");
    t.setTransform(1, 0, 0, 1, 0, 0);
    t.globalCompositeOperation = "source-over";
    if (persistence()) {
      t.globalCompositeOperation = "destination-out";
      t.fillStyle = "rgba(0,0,0,0.45)";
      t.fillRect(0, 0, width, height);
      t.globalCompositeOperation = "source-over";
    } else {
      t.clearRect(0, 0, width, height);
    }
    const list = drawMoving(t, width, height, ratio, s, c);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(still, 0, 0);
    ctx.globalCompositeOperation = "lighter";
    ctx.drawImage(trace, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    shown = { ...view, range: range() };

    if (now - lastHud > 500) { lastHud = now; drawHud(list); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  function drawHud(list) {
    const radar = store.state.radar;
    if (hud.tracks) hud.tracks.textContent = `${list.length} TRACK${list.length === 1 ? "" : "S"}`;
    if (!hud.poll) return;
    if (!radar || radar.age === null) {
      hud.poll.textContent = radar && radar.error ? `RADAR ${radar.error}` : "RADAR WAITING";
      return;
    }
    const age = Math.round(radar.age + (performance.now() - store.state.radarAt) / 1000);
    hud.poll.textContent = radar.error ? `${radar.error}, PICTURE ${age}S OLD` : `POLLED ${age}S AGO`;
  }

  // -- pointing, panning, zooming, focusing --

  function local(event) {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    return [(event.clientX - box.left) * ratio, (event.clientY - box.top) * ratio];
  }

  function hitAircraft([x, y]) {
    const ratio = window.devicePixelRatio || 1;
    for (const hit of hits) {
      if (Math.hypot(hit.x - x, hit.y - y) < 14 * ratio) return hit.hex;
      const l = hit.label;
      if (x >= l.x && x <= l.x + l.w && y >= l.y && y <= l.y + l.h) return hit.hex;
      for (let i = 1; i < hit.trail.length; i += 1) {
        if (nearSegment(x, y, hit.trail[i - 1], hit.trail[i]) < 6 * ratio) return hit.hex;
      }
    }
    return null;
  }

  canvas.addEventListener("pointerdown", (event) => {
    pointer.at = local(event);
    pointer.down = { at: pointer.at, panX: view.panX, panY: view.panY };
    pointer.before = pointer.moved;
    pointer.moved = false;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const at = local(event);
    pointer.at = at;
    if (pointer.down) {
      const { ratio, width, height } = size();
      const s = scale(width, height, ratio);
      const dx = at[0] - pointer.down.at[0];
      const dy = at[1] - pointer.down.at[1];
      if (Math.hypot(dx, dy) > 4 * ratio) pointer.moved = true;
      if (pointer.moved) {
        view.panX = pointer.down.panX - dx / s;
        view.panY = pointer.down.panY - dy / s;
        staticDirty = true;
      }
      return;
    }
    const over = placed.find((p) => at[0] >= p.x && at[0] <= p.x + p.w && at[1] >= p.y && at[1] <= p.y + p.h);
    const key = over ? over.key : null;
    if (key !== hovered) { hovered = key; staticDirty = true; }
    canvas.style.cursor = hitAircraft(at) ? "pointer" : pointer.down ? "grabbing" : "crosshair";
    if (hud.position) hud.position.textContent = positionText(at);
  });

  canvas.addEventListener("pointerup", (event) => {
    const at = local(event);
    if (pointer.down && !pointer.moved) {
      const hex = hitAircraft(at);
      if (hex) focus.toggle(hex);
    }
    pointer.down = null;
  });

  canvas.addEventListener("pointerleave", () => {
    if (hovered) { hovered = null; staticDirty = true; }
    if (hud.position) hud.position.textContent = "";
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const { ratio, width, height } = size();
    const at = local(event);
    const before = scale(width, height, ratio);
    const factor = Math.exp(-event.deltaY * 0.0015);
    view.nm = Math.min(Math.max(VIEW_MAX_NM, range()), Math.max(VIEW_MIN_NM, view.nm / factor));
    const after = scale(width, height, ratio);
    // Keep the point under the pointer where it is.
    const nx = view.panX + (at[0] - width / 2) / before;
    const ny = view.panY + (at[1] - height / 2) / before;
    view.panX = nx - (at[0] - width / 2) / after;
    view.panY = ny - (at[1] - height / 2) / after;
    staticDirty = true;
  }, { passive: false });

  function positionText(at) {
    const { ratio, width, height } = size();
    const s = scale(width, height, ratio);
    const x = view.panX + (at[0] - width / 2) / s;
    const y = view.panY + (at[1] - height / 2) / s;
    const nm = Math.hypot(x, y);
    const brg = (Math.round((Math.atan2(x, -y) * 180) / Math.PI) + 360) % 360;
    return `${String(brg).padStart(3, "0")}° ${nm.toFixed(1)} NM`;
  }

  // With no button for it, a double click is the way back from a pan. The
  // browser counts presses, not clicks: two quick pans from one spot, or a
  // click straight after a pan, also arrive as a double click and are not one.
  canvas.addEventListener("dblclick", (event) => {
    if (pointer.moved || pointer.before) return;
    recentre();
    // The readout is for the view on screen, and the pointer has not moved.
    if (hud.position) hud.position.textContent = positionText(local(event));
  });

  new ResizeObserver(() => { staticDirty = true; }).observe(canvas);
  store.subscribe((kind) => {
    if (kind === "all") {
      const airport = store.state.airport;
      if (airport && airport.icao !== mapFor) {
        recentre();
        loadMap(airport);
      }
      if (range() !== viewFor) recentre();
      staticDirty = true;
    } else if (kind === "prefs") {
      // A new range is a new picture: the view goes back to it.
      if (range() !== viewFor) recentre();
      staticDirty = true;
    }
  });

  return {
    recentre,
    redraw() { staticDirty = true; },
    // For tests: what is on screen, in screen pixels. `view` and the range
    // change with the event that changes them and `shown` with the next
    // frame, so the rest describes them once `shown` agrees with both.
    debug() {
      return {
        hits: hits.map((h) => ({ hex: h.hex, x: h.x, y: h.y })),
        placed, hovered, view: { ...view }, mapFor, loaded: Boolean(map),
        rings, home, symbols, shown,
        layers: map ? Object.fromEntries(Object.entries(map.lines).map(([k, v]) => [k, v.length])) : {},
      };
    },
  };
}

function nearSegment(x, y, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
