// The page's one frame clock (phase G, Task 4): a single
// requestAnimationFrame loop that every animated view hangs off, held to
// the frame rate setting (prefs.fps_max).
//
// A run happens when at least 1000 / fps_max ms, less 1 ms of slack, have
// passed since the last one, measured on the display's frame times (the
// timestamp requestAnimationFrame gives, not performance.now). The slack is
// for jitter: at 60 on a 60 Hz display every frame runs; at 60 on 120 Hz
// every other one, which is meant. 120 is the display's own rate, whatever
// it is: every frame runs.
//
// "The last one" is when it was due rather than when it came, by up to one
// frame of the cap, and never later than it came. Where frames come late or
// unevenly (headless WebKit's come 1 to 35 ms apart; headless Chromium's
// stall while the radar draws in software) counting from when each came
// would lose its lateness every time: at 15 it gave 12 a second. So the cap
// holds on average, and a run after a late one may follow it sooner. On a
// display that keeps time it is when it came, and nothing changes.
//
// main.js calls bindFrames(store) once; until then the cap is 60.

const SLACK_MS = 1;
const UNCAPPED = 120;

const callbacks = new Set();
let fpsMax = () => 60;
let started = false;
let last = -Infinity;

export function bindFrames(store) {
  fpsMax = () => store.state.prefs.fps_max;
}

// `fn(now)` on every run, `now` being the frame's timestamp. Returns a
// function that takes it off again.
export function onFrame(fn) {
  callbacks.add(fn);
  if (!started) { started = true; requestAnimationFrame(tick); }
  return () => callbacks.delete(fn);
}

function tick(now) {
  requestAnimationFrame(tick);
  const fps = fpsMax();
  if (fps < UNCAPPED) {
    const every = 1000 / fps;
    if (now - last < every - SLACK_MS) return;
    last = Math.min(now, Math.max(last + every, now - every));
  } else {
    last = now;
  }
  // One view that throws does not stop the others, nor the clock; the error
  // still reaches the page's error handlers.
  for (const fn of [...callbacks]) {
    try {
      fn(now);
    } catch (error) {
      setTimeout(() => { throw error; });
    }
  }
}
