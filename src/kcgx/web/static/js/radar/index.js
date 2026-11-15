// The radar (spec, Radar; Visual language; Rendering). Our own vector
// renderer on one canvas, in parts:
//
//   index.js   mounting, the canvases and their size, the frame loop and the
//              order the layers are put together in, the HUD, and what the
//              store tells the radar
//   still.js   the static layer: map, rings, labels, the home airport
//   moving.js  the moving layer: aircraft and trails; and the tags' layer
//   view.js    the view in nm, the pointer: pan, zoom, recentre, hit tests
//   draw.js    what the two layers share: the font, label boxes
//   info.js    the focused aircraft's data box, a page element over the radar
//
// The static layer is drawn into an offscreen canvas when it changes and
// copied each frame. The moving one is drawn every frame. With display
// VECTOR or CRT the moving layer fades instead of clearing, which is the
// phosphor persistence, by a half-life (prefs.burn_in). Both are light, added to the screen. The flight
// tags are drawn every frame onto a layer of their own, cleared each time,
// and laid over the rest as they are (phase G decision 8).
//
// The parts share one object, `radar`, made here. This file puts the
// shared core on it: the canvas, the store, the HUD, the range, whether the
// static layer is to be drawn again, the canvases `size()` keeps at the
// screen's size, and what the last frame drew. Each of view.js, still.js
// and moving.js then adds its own part in its `init(radar)`, which also
// binds that module's listeners and may return `{ tick(now), post(now),
// debug() }`, each optional. The inits run in that order, before the first
// frame. Every frame is counted, then runs each tick in the same order, is
// drawn, and ends with each post in that order (one that reads this frame's
// `radar.now` or `shown` goes there). `debug()` is the core's and every
// module's put together, a key from two of them being an error.
//
// Pointer and hit maths take their ratio of canvas pixels to CSS pixels
// from `size()`, never from devicePixelRatio, so a render scale reaches them.
// That ratio is the display's times the render scale (theme.js
// renderScale(), by prefs.aa: OFF half, scaled up stepped, ON the
// display's own, SUPER twice), and every canvas in `radar.canvases` is that
// many pixels to a CSS pixel as it stands on the screen, the page's zoom
// (prefs.ui_zoom) included, so the radar is as sharp at any zoom.
//
// The objects on `radar` (the view, the pointer, the lists of what was
// drawn) are changed in place and never replaced, so a part may keep hold
// of one. Values (`map`, `project`, `shown`, `hovered`, ...) are set anew.

import { colours, reducedMotion, renderScale } from "../theme.js";
import { onFrame } from "../frames.js";
import { FONT } from "./draw.js";
import { drawStatic, init as initStill } from "./still.js";
import { drawMoving, init as initMoving } from "./moving.js";
import { cssZoomFix, init as initView, recentre, scale } from "./view.js";

const FADE_FRAMES = 30; // frames the persistence fade's interval is the mean of
const FADE_MAX_MS = 100; // the longest interval it counts; after a longer one the layer is cleared
const MAX_PIXELS = 8e6; // the most a radar canvas's backing store has, width times height

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

// The HUD's first line: how long ago the radar was polled, `age` in whole
// seconds or null before any picture, and what went wrong if anything did.
const seconds = (n) => `${n} SECOND${n === 1 ? "" : "S"}`;
export function pollWords(polled, age) {
  if (!polled || age === null) return polled && polled.error ? `RADAR ${polled.error}` : "RADAR WAITING";
  return polled.error ? `${polled.error}, PICTURE ${seconds(age)} OLD` : `${seconds(age)} AGO`;
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

  // The canvases' backing stores: the canvas's size on the screen, times
  // the ratio. Under a CSS zoom on .page, Chromium's getBoundingClientRect
  // gives the size as zoomed and WebKit's as not, so the rectangle is put
  // right by `cssZoomFix` (the zoom over the canvas, over how much of it the
  // rectangle already has). With the render scale under 1, the screen
  // scales the canvas up stepped (image-rendering: pixelated).
  //
  // No canvas is over MAX_PIXELS: where the ratio would make one so (SUPER
  // on a 2x display gives 4, and 1440 by 900 then some 9.6 million pixels
  // each, five canvases of them), the ratio is cut to the one that comes to
  // it, the same both ways, and the ratio returned is the one cut, so the
  // pointer's maths and every size drawn by the ratio follow.
  let rendering = "";
  function size() {
    const scaled = renderScale();
    let ratio = (window.devicePixelRatio || 1) * scaled;
    const box = canvas.getBoundingClientRect();
    const k = cssZoomFix(canvas, box);
    const area = box.width * k * box.height * k;
    if (area * ratio * ratio > MAX_PIXELS) {
      ratio = Math.sqrt(MAX_PIXELS / area);
      // Rounded to whole pixels, each side may come out up to half a pixel more.
      while (Math.round(box.width * k * ratio) * Math.round(box.height * k * ratio) > MAX_PIXELS) ratio *= 0.9995;
    }
    const width = Math.max(1, Math.round(box.width * k * ratio));
    const height = Math.max(1, Math.round(box.height * k * ratio));
    for (const c of radar.canvases) {
      if (c.width !== width || c.height !== height) { c.width = width; c.height = height; radar.staticDirty = true; }
    }
    const wanted = scaled < 1 ? "pixelated" : "";
    if (wanted !== rendering) { rendering = wanted; canvas.style.imageRendering = wanted; }
    return { ratio, width, height };
  }

  // -- the parts --

  const hooks = [initView(radar), initStill(radar), initMoving(radar)].filter(Boolean);

  // -- the frame loop --

  // Persistence: with display VECTOR or CRT, and prefs.burn_in over 0, the
  // moving layer fades rather than clears. burn_in is the fade's half-life
  // in ms (phase G decision 15), so it looks the same at any frame rate:
  // each frame takes 1 - 0.5 ^ (elapsed / half-life) of what is there.
  // The default, 19, is phase F's 0.45 a frame at 60 Hz (0.55 left after
  // 16.7 ms is a half-life of 19.3 ms).
  //
  // "Elapsed" is the mean interval of the last FADE_FRAMES frames, to the
  // half ms, not each frame's own: where frames come unevenly (headless
  // WebKit's at 10 and 20 ms in turn, capped to 60) a fade that changed
  // from frame to frame would make a still picture's edges shimmer, and
  // the same fade a frame comes to the same over time.
  //
  // After a gap, an interval over FADE_MAX_MS (a hidden tab, a long frame),
  // the layer is cleared that frame: what is on it is of where the traffic
  // was then, and would otherwise linger, faded by the mean, as a ghost.
  // That interval is left out of the mean, so the frames after it fade as
  // the ones before. A new frame rate cap (prefs.fps_max) starts the mean
  // again, from that frame's own interval. Returns the interval to fade by,
  // or Infinity to clear.
  function frameMs(now, fps) {
    if (fps !== fadeFps) { fadeFps = fps; intervals.length = 0; }
    const gap = lastFrame === null ? Infinity : now - lastFrame;
    lastFrame = now;
    if (gap > FADE_MAX_MS) return Infinity;
    intervals.push(gap);
    if (intervals.length > FADE_FRAMES) intervals.shift();
    return fadeMean();
  }
  const fadeMean = () => (intervals.length
    ? Math.round((2 * intervals.reduce((a, b) => a + b)) / intervals.length) / 2 : null);

  function persistence(prefs) {
    const display = document.documentElement.dataset.display;
    return display !== "OFF" && !reducedMotion() && prefs.burn_in > 0;
  }

  let lastHud = 0;
  let lastFrame = null; // the last frame's time, for the fade
  let fadeFps = null; // the frame rate cap its intervals were counted under
  const intervals = []; // and the last FADE_FRAMES frames' intervals, ms
  function frame(now) {
    frames += 1; // first: a tick that throws is still a frame, and a test waiting on one sees it
    for (const h of hooks) if (h.tick) h.tick(now);
    const { ratio, width, height } = size();
    if (radar.staticDirty) drawStatic(radar, now);
    const c = colours();
    const { prefs } = store.state;
    const s = scale(radar, width, height, ratio);
    const { trace, still } = radar;

    const t = trace.getContext("2d");
    t.setTransform(1, 0, 0, 1, 0, 0);
    t.globalCompositeOperation = "source-over";
    const elapsed = frameMs(now, prefs.fps_max);
    if (persistence(prefs) && elapsed !== Infinity) {
      t.globalCompositeOperation = "destination-out";
      t.fillStyle = `rgba(0,0,0,${1 - 0.5 ** (elapsed / prefs.burn_in)})`;
      t.fillRect(0, 0, width, height);
      t.globalCompositeOperation = "source-over";
    } else {
      t.clearRect(0, 0, width, height);
    }
    const { drawn } = drawMoving(radar, t, width, height, ratio, s, c, prefs);

    // The map, the aircraft added to it, and the tags over both.
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(still, 0, 0);
    ctx.globalCompositeOperation = "lighter";
    ctx.drawImage(trace, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.drawImage(radar.tags, 0, 0);
    radar.shown = { ...radar.view, range: range() };

    if (now - lastHud > 500) { lastHud = now; drawHud(drawn); }
    for (const h of hooks) if (h.post) h.post(now);
  }
  onFrame(frame);

  // `drawn` the aircraft on the radar: those ground_mode HIDE or the
  // tracks table's filters leave out are not counted.
  function drawHud(drawn) {
    const polled = store.state.radar;
    if (hud.tracks) hud.tracks.textContent = `${drawn} TRACK${drawn === 1 ? "" : "S"}`;
    if (!hud.poll) return;
    const age = !polled || polled.age === null
      ? null : Math.round(polled.age + (performance.now() - store.state.radarAt) / 1000);
    hud.poll.textContent = pollWords(polled, age);
  }

  // -- what the store says --

  new ResizeObserver(() => { radar.staticDirty = true; }).observe(canvas);
  store.subscribe((kind) => {
    if (kind === "all" || kind === "prefs") radar.staticDirty = true;
  });

  return {
    recentre() { recentre(radar); },
    redraw() { radar.staticDirty = true; },
    // For tests: a part of the test's own, as if it were one of the modules.
    // `init(radar)` runs now; its hooks run after the others'. Returns a
    // function that takes them off again.
    hook(init) {
      const h = init(radar) || {};
      hooks.push(h);
      return () => { const at = hooks.indexOf(h); if (at >= 0) hooks.splice(at, 1); };
    },
    // For tests: what is on screen, in screen pixels. `view` and the range
    // change with the event that changes them and `shown` with the next
    // frame, so the rest describes them once `shown` agrees with both.
    debug() {
      // fade_ms: the interval the persistence fade goes by, ms (null before two frames).
      return mergeDebug([{ shown: radar.shown, frames, font: FONT, fade_ms: fadeMean() }, ...hooks.map((h) => (h.debug ? h.debug() : {}))]);
    },
  };
}
