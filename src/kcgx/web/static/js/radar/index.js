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
// The parts share one object, `radar`, made here. This file puts the
// shared core on it: the canvas, the store, the HUD, the range, whether the
// static layer is to be drawn again, the canvases `size()` keeps at the
// screen's size, and what the last frame drew. Each of view.js, still.js
// and moving.js then adds its own part in its `init(radar)`, which also
// binds that module's listeners and may return `{ tick(now), debug() }`.
// The inits run in that order, before the first frame; every frame starts
// with each tick in the same order, and `debug()` is the core's and every
// module's put together, a key from two of them being an error.
//
// The objects on `radar` (the view, the pointer, the lists of what was
// drawn) are changed in place and never replaced, so a part may keep hold
// of one. Values (`map`, `project`, `shown`, `hovered`, ...) are set anew.

import { colours, reducedMotion } from "../theme.js";
import { onFrame } from "../frames.js";
import { paintBox } from "./draw.js";
import { drawStatic, init as initStill } from "./still.js";
import { drawMoving, init as initMoving } from "./moving.js";
import { init as initView, recentre, scale } from "./view.js";

// One object from several, each key from one only.
export function mergeDebug(parts) {
  const out = {};
  for (const part of parts) {
    for (const [key, value] of Object.entries(part)) {
      if (key in out) throw new Error(`radar debug(): ${key} is given twice`);
      out[key] = value;
    }
  }
  return out;
}

export function mountRadar(canvas, store, { hud = {} } = {}) {
  const range = () => store.state.prefs.range_nm;
  const radar = {
    canvas, store, hud, range,
    staticDirty: true,
    canvases: [canvas], // every canvas size() keeps at the screen's size; an init adds its own
    shown: null, // the view and the range, as the last frame drew them
    boxed: (item) => store.state.prefs.box_items.includes(item),
    size,
  };
  let frames = 0; // drawn so far, for tests of the frame rate

  // -- sizes --

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    for (const c of radar.canvases) {
      if (c.width !== width || c.height !== height) { c.width = width; c.height = height; radar.staticDirty = true; }
    }
    return { ratio, width, height };
  }

  // -- the parts --

  const hooks = [initView(radar), initStill(radar), initMoving(radar)].filter(Boolean);
  const ticks = hooks.filter((h) => h.tick);

  // -- the frame loop --

  function persistence() {
    const display = document.documentElement.dataset.display;
    return display !== "OFF" && !reducedMotion();
  }

  let lastHud = 0;
  function frame(now) {
    for (const h of ticks) h.tick(now);
    frames += 1;
    const { ratio, width, height } = size();
    if (radar.staticDirty) drawStatic(radar, now);
    const c = colours();
    const { prefs } = store.state;
    const s = scale(radar, width, height, ratio);
    const { trace, still } = radar;

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
    radar.shown = { ...radar.view, range: range() };

    if (now - lastHud > 500) { lastHud = now; drawHud(list); }
  }
  onFrame(frame);

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

  // -- what the store says --

  new ResizeObserver(() => { radar.staticDirty = true; }).observe(canvas);
  store.subscribe((kind) => {
    if (kind === "all" || kind === "prefs") radar.staticDirty = true;
  });

  return {
    recentre() { recentre(radar); },
    redraw() { radar.staticDirty = true; },
    // For tests: what is on screen, in screen pixels. `view` and the range
    // change with the event that changes them and `shown` with the next
    // frame, so the rest describes them once `shown` agrees with both.
    debug() {
      return mergeDebug([{ shown: radar.shown, frames }, ...hooks.map((h) => (h.debug ? h.debug() : {}))]);
    },
  };
}
