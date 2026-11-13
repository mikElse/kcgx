// The boot animation (phase G Task 14, decision 1): the vector scene
// (boot-scene.js) on a cover over the whole window, once per launch, while
// the page beneath connects and fills in.
//
// <html data-booting> (index.html) keeps the page and its dialogs at
// opacity 0 from the first paint, so nothing shows in the default palette
// before the server's prefs are in. The first snapshot, or 1.5 s without
// one, decides once whether to play: the snapshot's `boot` (the first page
// since the server started, kcgx.hub) and `boot_anim`, and no reduced
// motion. A later prefs frame or snapshot changes nothing. Played, it runs
// LENGTH s on frames.js's clock and fades out over FADE_MS as the page fades
// in; a key or a press anywhere does the same at once (a modifier key
// alone does not). Not played, the page shows at once. Done, it gives its
// canvases' backing stores back.
//
// index.html's head has a fallback of its own: if nothing here has decided
// by 3 s (main.js failed to load, or threw before mounting this), it takes
// data-booting off, so an error is never a black window. Deciding calls it
// off (window.kcgxBootFallback).
//
// window.kcgx.boot is for the tests: `state` (waiting, playing, leaving,
// done, or none when it does not play), `t` (playback seconds), `frames`,
// `hold(t)`, `seek(t)`, `at(x, y)` (a scene point in canvas pixels),
// `drawMs` (the last frames' drawing times, for measuring) and `canvases`
// (the [width, height] of each canvas it still holds).

import { authored, fit, frame, LENGTH } from "./boot-scene.js";
import { onFrame } from "./frames.js";
import { colours, glowBlur, reducedMotion, renderScale } from "./theme.js";

const WAIT_MS = 1500;
const FADE_MS = 600; // also cockpit.css's G:BOOT transitions
const MEASURED = 120;
// Keys that are half a shortcut, or a state, rather than a press.
const MODIFIERS = new Set(["Shift", "Control", "Alt", "AltGraph", "Meta", "OS", "CapsLock", "Fn", "FnLock", "NumLock", "ScrollLock", "Hyper", "Super", "Symbol", "SymbolLock"]);

// What waits for the boot to be over: `fn` runs once the cover has gone, or
// at once when it is not played (or already over). main.js opens the
// airport search from a #airport link this way, so the sheet's backdrop is
// never over the animation, nor its focus in an input nobody can see.
let over = false;
const afterwards = [];
export function afterBoot(fn) {
  if (over) fn();
  else afterwards.push(fn);
}
function ended() {
  over = true;
  for (const fn of afterwards.splice(0)) {
    try { fn(); } catch (error) { console.error(error); }
  }
}

// How much of the canvas a frame `ms` after the last fades away: burn_in is
// the half-life in ms (decision 15), so 19, the default, takes 0.45 a frame
// at 60 Hz, as the radar's moving layer did, and the same in time at any
// frame rate. 0 is no persistence at all.
export function fadeFor(ms, halfLife) {
  return halfLife > 0 ? 1 - 0.5 ** (ms / halfLife) : 1;
}

function sized(canvas, width, height) {
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
}

// Whether this canvas has filters (CanvasRenderingContext2D.filter).
let filtering = null;
function filters(ctx) {
  if (filtering === null) {
    ctx.filter = "blur(1px)";
    filtering = ctx.filter === "blur(1px)";
    ctx.filter = "none";
  }
  return filtering;
}

export function mountBoot(cover, store) {
  const root = document.documentElement;
  let canvas = cover.querySelector("canvas");
  let state = "waiting";
  let start = null; // the frame time playback started from
  let held = null; // a playback time to stay at, for the tests
  let lastNow = null; // the last frame's time
  let lastDrawn = null; // when the canvas was last drawn, for the burn-in
  let t = 0;
  let frames = 0;
  let fontsIn = false;
  let failed = false; // whether a frame has thrown (written to the console once)
  let stop = () => {};
  const drawMs = [];
  // Where the canvas has filters: the scene small, and its glow.
  let small = document.createElement("canvas");
  let soft = document.createElement("canvas");

  const unsubscribe = store.subscribe((kind, _detail, s) => {
    if (kind === "all") decide(Boolean(s.boot && s.prefs.boot_anim) && !reducedMotion());
  });
  const timer = setTimeout(() => decide(false), WAIT_MS);

  function decide(play) {
    if (state !== "waiting") return;
    unsubscribe();
    clearTimeout(timer);
    clearTimeout(window.kcgxBootFallback);
    if (!play) {
      state = "none";
      cover.remove();
      release();
      root.removeAttribute("data-booting");
      ended();
      return;
    }
    state = "playing";
    cover.hidden = false;
    // KCGX is drawn in the display face (--font-display, FONT's), once the
    // page's faces are in: a face is fetched only when it is in use.
    const family = display();
    document.fonts.load(`160px ${family}`).catch(() => {}).then(() => document.fonts.ready).then(() => {
      fontsIn = true;
    });
    addEventListener("keydown", skip, true);
    addEventListener("pointerdown", skip, true);
    stop = onFrame(tick);
  }

  function tick(now) {
    if (start === null) start = now;
    lastNow = now;
    t = held ?? (now - start) / 1000;
    // The end first, so a frame that cannot be drawn never keeps the cover up.
    if (t >= LENGTH && held === null) { leave(); return; }
    const begun = performance.now();
    try {
      draw(now);
    } catch (error) {
      if (!failed) console.error("boot: a frame failed to draw", error);
      failed = true;
    }
    drawMs.push(performance.now() - begun);
    if (drawMs.length > MEASURED) drawMs.shift();
    frames += 1;
  }

  // The canvases' backing stores back (at 2x and SUPER, tens of MB), and
  // nothing kept of them: the tests' handle on this outlives the cover.
  function release() {
    for (const each of [canvas, small, soft]) {
      if (each) { each.width = 0; each.height = 0; }
    }
    canvas = small = soft = null;
  }

  // Backing store by the render scale (decision 6), as the radar's: at OFF
  // half the pixels, scaled up hard; at SUPER twice.
  function draw(now) {
    const scale = renderScale();
    const ratio = (window.devicePixelRatio || 1) * scale;
    canvas.style.imageRendering = scale < 1 ? "pixelated" : "";
    const width = Math.max(1, Math.round(cover.clientWidth * ratio));
    const height = Math.max(1, Math.round(cover.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
      lastDrawn = null;
    }
    const ctx = canvas.getContext("2d");
    const fade = lastDrawn === null ? 1 : fadeFor(now - lastDrawn, store.state.prefs.burn_in);
    lastDrawn = now;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (fade >= 1) {
      ctx.clearRect(0, 0, width, height);
    } else {
      // Fading to clear: the cover's own --wall shows through.
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = `rgba(0, 0, 0, ${fade})`;
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = "source-over";
    }
    // The scene is line art of the world, as the radar's map is: the map
    // layer's glow. A shadow on each stroke is what the radar does, and is
    // what WebKit gets. Where the canvas has filters (Chromium), the glow is
    // the scene drawn at half the CSS pixels, blurred there and scaled up
    // under the scene drawn sharp: a glow is soft, and it is the blur's
    // cost that grows with the pixels. In headless Chromium's software
    // canvas it gives 60 frames a second at 1x where shadows gave 30 to 60.
    const glow = glowBlur("map") * ratio;
    const font = fontsIn ? display() : null;
    const T = authored(t);
    if (glow > 0 && filters(ctx)) {
      const k = Math.max(1, 2 * ratio);
      const w = Math.ceil(width / k), h = Math.ceil(height / k);
      sized(small, w, h);
      sized(soft, w, h);
      const s = small.getContext("2d");
      s.setTransform(1, 0, 0, 1, 0, 0);
      s.clearRect(0, 0, w, h);
      frame(s, T, colours(), { ratio: ratio / k, font, scale: 1 / k, size: [width, height] });
      const g = soft.getContext("2d");
      g.clearRect(0, 0, w, h);
      // A shadow's blur is twice the Gaussian's deviation, a filter's blur() the deviation.
      g.filter = `blur(${glow / 2 / k}px)`;
      g.drawImage(small, 0, 0);
      g.filter = "none";
      ctx.drawImage(soft, 0, 0, w * k, h * k);
      frame(ctx, T, colours(), { ratio, font });
    } else {
      frame(ctx, T, colours(), { glow: glow / ratio, ratio, font });
    }
  }

  function display() {
    return getComputedStyle(root).getPropertyValue("--font-display").trim();
  }

  function skip(event) {
    if (state !== "playing") return;
    if (event.type === "keydown" && MODIFIERS.has(event.key)) return;
    // The press is the skip's: it does not reach the cockpit under the cover.
    event.preventDefault();
    event.stopPropagation();
    leave();
  }

  function leave() {
    if (state !== "playing") return;
    state = "leaving";
    stop();
    removeEventListener("keydown", skip, true);
    removeEventListener("pointerdown", skip, true);
    root.setAttribute("data-boot-fade", "");
    cover.classList.add("leaving");
    root.removeAttribute("data-booting");
    setTimeout(() => {
      cover.remove();
      release();
      root.removeAttribute("data-boot-fade");
      state = "done";
      ended();
    }, FADE_MS);
  }

  return {
    get state() { return state; },
    get t() { return t; },
    get frames() { return frames; },
    get drawMs() { return [...drawMs]; },
    get canvases() { return [canvas, small, soft].filter(Boolean).map((c) => [c.width, c.height]); },
    hold(at) {
      if (at === null && held !== null && lastNow !== null) start = lastNow - held * 1000;
      held = at;
    },
    seek(at) {
      start = (lastNow ?? performance.now()) - at * 1000;
    },
    at(x, y) {
      if (!canvas) return [NaN, NaN];
      const view = fit(canvas.width, canvas.height);
      return [view.x + x * view.s, view.y + y * view.s];
    },
  };
}
