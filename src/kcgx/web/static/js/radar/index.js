// The radar (spec, Radar; Visual language; Rendering). Our own vector
// renderer on one canvas, in parts:
//
//   index.js   mounting, the canvases and their size, the frame loop and the
//              order the layers are put together in, the HUD, and what the
//              store tells the radar
//   still.js   the static layer: map, rings, labels, the home airport
//   moving.js  the moving layer: aircraft, trails, tags
//   view.js    the view in nm, the pointer: pan, zoom, recentre, hit tests
//   draw.js    what the two layers share: the font, label boxes
//
// The static layer is drawn into an offscreen canvas when it changes and
// copied each frame. The moving one is drawn every frame. With display
// VECTOR or CRT the moving layer fades instead of clearing, which is the
// phosphor persistence.
//
// The parts share one object, `radar`, made here: the store, the canvases,
// the view and what the last drawing left for the pointer and for tests.

import { colours, reducedMotion } from "../theme.js";
import { paintBox } from "./draw.js";
import { drawStatic, loadMap } from "./still.js";
import { drawMoving } from "./moving.js";
import { bindPointer, newView, recentre, scale } from "./view.js";

export function mountRadar(canvas, store, { hud = {} } = {}) {
  const range = () => store.state.prefs.range_nm;
  const radar = {
    canvas, store, hud, range,
    view: newView(range()),
    viewFor: 0, // the range the view was last reset for
    map: null, // decoded geo for the current airport
    mapFor: "",
    project: null,
    drawOnFrom: 0,
    staticDirty: true,
    hovered: null, // a placed label's key
    // A label is what `claim` gives: { x, y, w, h, boxed, box: {x, y, w, h} or null }.
    placed: [], // [{ key, ...label }]
    rings: [], // [{ nm, r, bright, text, label: {...label, at: [x, baseline]} or null }], as last drawn
    home: { x: 0, y: 0, r: 0 }, // the airport and its ring, as last drawn
    symbols: {}, // kind -> how many are on screen, as last drawn
    shown: null, // the view and the range, as the last frame drew them
    hits: [], // [{ hex, x, y, tag: {lines, ...label} or null, trail: [[x, y]] }]
    // moved: the press now down, or the last one, became a drag. before: the
    // press ahead of it did. at: where the pointer last was.
    pointer: { down: null, moved: false, before: false, at: [0, 0] },
    still: document.createElement("canvas"),
    trace: document.createElement("canvas"), // the moving layer, for persistence
    bare: document.createElement("canvas"), // the aircraft's lines in one colour, before their glow
    boxed: (item) => store.state.prefs.box_items.includes(item),
    size,
  };
  radar.viewFor = radar.view.nm;
  const { view, still, trace, bare } = radar;

  // -- sizes --

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    for (const c of [canvas, still, trace, bare]) {
      if (c.width !== width || c.height !== height) { c.width = width; c.height = height; radar.staticDirty = true; }
    }
    return { ratio, width, height };
  }

  // -- the frame loop --

  function persistence() {
    const display = document.documentElement.dataset.display;
    return display !== "OFF" && !reducedMotion();
  }

  let lastHud = 0;
  function frame(now) {
    const { ratio, width, height } = size();
    if (radar.staticDirty) drawStatic(radar, now);
    const c = colours();
    const { prefs } = store.state;
    const s = scale(radar, width, height, ratio);

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
    const { list, boxes } = drawMoving(radar, t, width, height, ratio, s, c, prefs);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(still, 0, 0);
    // The tags' boxes go between the layers: over the map, under the
    // aircraft, which are added to the screen and would not show black.
    for (const { box, colour, alpha } of boxes) paintBox(ctx, box, colour, ratio, prefs, alpha);
    ctx.globalCompositeOperation = "lighter";
    ctx.drawImage(trace, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    radar.shown = { ...view, range: range() };

    if (now - lastHud > 500) { lastHud = now; drawHud(list); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  function drawHud(list) {
    const polled = store.state.radar;
    if (hud.tracks) hud.tracks.textContent = `${list.length} TRACK${list.length === 1 ? "" : "S"}`;
    if (!hud.poll) return;
    if (!polled || polled.age === null) {
      hud.poll.textContent = polled && polled.error ? `RADAR ${polled.error}` : "RADAR WAITING";
      return;
    }
    const age = Math.round(polled.age + (performance.now() - store.state.radarAt) / 1000);
    hud.poll.textContent = polled.error ? `${polled.error}, PICTURE ${age}S OLD` : `POLLED ${age}S AGO`;
  }

  // -- the pointer, and what the store says --

  bindPointer(radar);

  new ResizeObserver(() => { radar.staticDirty = true; }).observe(canvas);
  store.subscribe((kind) => {
    if (kind === "all") {
      const airport = store.state.airport;
      if (airport && airport.icao !== radar.mapFor) {
        recentre(radar);
        loadMap(radar, airport);
      }
      if (range() !== radar.viewFor) recentre(radar);
      radar.staticDirty = true;
    } else if (kind === "prefs") {
      // A new range is a new picture: the view goes back to it.
      if (range() !== radar.viewFor) recentre(radar);
      radar.staticDirty = true;
    }
  });

  return {
    recentre() { recentre(radar); },
    redraw() { radar.staticDirty = true; },
    // For tests: what is on screen, in screen pixels. `view` and the range
    // change with the event that changes them and `shown` with the next
    // frame, so the rest describes them once `shown` agrees with both.
    debug() {
      const { map } = radar;
      return {
        hits: radar.hits.map((h) => ({ hex: h.hex, x: h.x, y: h.y, tag: h.tag })),
        placed: radar.placed, hovered: radar.hovered, view: { ...view }, mapFor: radar.mapFor, loaded: Boolean(map),
        rings: radar.rings, home: radar.home, symbols: radar.symbols, shown: radar.shown,
        layers: map ? Object.fromEntries(Object.entries(map.lines).map(([k, v]) => [k, v.length])) : {},
      };
    },
  };
}
