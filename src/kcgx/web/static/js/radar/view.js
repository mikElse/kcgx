// The view and the pointer: where the radar looks (`radar.view`, held in
// nautical miles), how screen pixels map to it, and what the pointer does
// to it: drag to pan, wheel to zoom about the pointer, double click to
// recentre, click an aircraft to focus it, click a place to centre it,
// hover a label to brighten it, and the bearing and distance under the
// pointer.
//
// The view moves to where it is sent (`goTo`) over prefs.view_ease's time,
// eased in and out (phase G decision 21); a wheel or a drag ends a move.
// Focusing an aircraft, here or in the table, sends the view to it at
// prefs.follow_nm and follows it (decision 10): each frame's drawing
// leaves where it is (`radar.now`), and the next frame's view is centred
// there. A drag ends the following and keeps the focus; the wheel zooms
// about the aircraft and keeps it. Unfocusing sends the view back to where
// it was before the focus; a double click recentres on the airport, ends
// the following and forgets that view. The focused aircraft's data box
// (radar/info.js) is placed after each frame too.
//
// `radar` is the shared state `mountRadar` makes (see radar/index.js);
// `init` adds this module's part of it.

import { focus } from "../focus.js";
import { reducedMotion } from "../theme.js";
import { mountInfo } from "./info.js";

const VIEW_MIN_NM = 0.25; // the closest view, this far from the centre to the nearer edge: the runways up close
const VIEW_MAX_NM = 160; // the widest, or the range if that is wider
const EDGE_PX = 18; // kept clear between the view's distance and the nearer edge
const WHEEL_RATE = 0.0015; // the view's distance shrinks by e^(this) a unit of wheel, at zoom_speed 100
const EASE_MS = { OFF: 0, QUICK: 250, SMOOTH: 600 }; // a view move's time, by prefs.view_ease

// The range is a setting (prefs.range_nm). The view is held in nautical
// miles: `nm` from the centre to the nearer edge, less EDGE_PX. It starts
// at the range and returns to it; pan is in nm too.
export function newView(range) {
  return { nm: range, panX: 0, panY: 0 };
}

// This module's part of `radar`, its pointer handlers, and its say in what
// the store changes: a new range is a new picture, and the view goes back
// to it.
export function init(radar) {
  radar.view = newView(radar.range());
  radar.viewFor = radar.view.nm; // the range the view was last reset for
  // moved: the press now down, or the last one, became a drag. before: the
  // press ahead of it did. at: where the pointer last was.
  radar.pointer = { down: null, moved: false, before: false, at: [0, 0] };
  // The move under way: from and to { nm, x, y } (x and y are the pan), over
  // `ms` from the frame `start` (null until its first). null when none is.
  radar.ease = null;
  radar.following = false; // the view keeps the focused aircraft at its centre
  radar.followAt = null; // where it was last drawn, in nm
  radar.unfocused = null; // the view from before the focus, { nm, x, y }, to go back to
  bindPointer(radar);
  focus.subscribe((hex) => focused(radar, hex));
  radar.store.subscribe((kind) => {
    if ((kind === "all" || kind === "prefs") && radar.range() !== radar.viewFor) recentre(radar);
  });
  const placeInfo = mountInfo(radar);
  return {
    tick: (now) => step(radar, now),
    post: () => { follow(radar); placeInfo(); },
    debug: () => ({ view: { ...radar.view }, following: radar.following, easing: Boolean(radar.ease) }),
  };
}

// Pixels per nm: the view's distance fits the shorter side.
export function scale(radar, width, height, ratio) {
  return Math.max(0, Math.min(width, height) / 2 - EDGE_PX * ratio) / radar.view.nm;
}

export function toScreen(radar, xy, s, width, height) {
  const { view } = radar;
  return [width / 2 + (xy[0] - view.panX) * s, height / 2 + (xy[1] - view.panY) * s];
}

// Back to the whole range, about the airport, at once. A drag that is
// under way (the range or the airport can change beneath one) carries on
// from here. A move or the following ends, and the view from before the
// focus is forgotten: this is the view now.
export function recentre(radar) {
  const { view, pointer } = radar;
  view.nm = radar.range();
  view.panX = 0;
  view.panY = 0;
  radar.viewFor = view.nm;
  radar.ease = null;
  radar.following = false;
  radar.unfocused = null;
  if (pointer.down) pointer.down = { at: pointer.at, panX: 0, panY: 0 };
  radar.staticDirty = true;
}

// -- moving the view -------------------------------------------------------------

function easeMs(radar) {
  return reducedMotion() ? 0 : EASE_MS[radar.store.state.prefs.view_ease] || 0;
}

const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function put(radar, { nm, x, y }) {
  const { view } = radar;
  if (view.nm === nm && view.panX === x && view.panY === y) return;
  view.nm = nm;
  view.panX = x;
  view.panY = y;
  radar.staticDirty = true;
}

// Send the view to { nm, x, y } (x and y the pan, in nm) over `ms`: at once
// when that is 0, or else from the next frame on.
export function goTo(radar, to, ms = easeMs(radar)) {
  const { view } = radar;
  if (ms <= 0) {
    radar.ease = null;
    put(radar, to);
    return;
  }
  radar.ease = { from: { nm: view.nm, x: view.panX, y: view.panY }, to: { ...to }, ms, start: null };
}

// At the start of a frame: the view where the move under way has it by
// now, or on the aircraft it follows. The distance eases on a log scale, so
// a zoom looks as even going in as going out.
function step(radar, now) {
  const { ease } = radar;
  if (ease) {
    if (ease.start === null) ease.start = now;
    const t = Math.min(1, Math.max(0, (now - ease.start) / ease.ms));
    const { from, to } = ease;
    if (t >= 1) {
      radar.ease = null;
      put(radar, to);
      return;
    }
    const k = easeInOutCubic(t);
    put(radar, {
      nm: from.nm === to.nm ? to.nm : Math.exp(Math.log(from.nm) + (Math.log(to.nm) - Math.log(from.nm)) * k),
      x: from.x + (to.x - from.x) * k,
      y: from.y + (to.y - from.y) * k,
    });
  } else if (radar.following && radar.followAt) {
    put(radar, { nm: radar.view.nm, x: radar.followAt[0], y: radar.followAt[1] });
  }
}

// After a frame: where the followed aircraft was drawn, which the next
// frame centres, and which a move to it heads for.
function follow(radar) {
  if (!radar.following) return;
  const ac = radar.now.find((one) => one.hex === focus.hex);
  if (!ac) return;
  radar.followAt = ac.now;
  if (radar.ease) {
    radar.ease.to.x = ac.now[0];
    radar.ease.to.y = ac.now[1];
  }
}

// The focus changed, here or in the table: follow the new one at the
// follow radius from where it was last drawn, or go back to the view from
// before there was one.
function focused(radar, hex) {
  const { view } = radar;
  if (hex) {
    if (!radar.unfocused) radar.unfocused = { nm: view.nm, x: view.panX, y: view.panY };
    const ac = radar.now.find((one) => one.hex === hex);
    radar.following = true;
    radar.followAt = ac ? ac.now : null;
    const at = ac ? ac.now : [view.panX, view.panY];
    goTo(radar, { nm: zoomed(radar, radar.store.state.prefs.follow_nm), x: at[0], y: at[1] });
    return;
  }
  radar.following = false;
  radar.followAt = null;
  const back = radar.unfocused;
  radar.unfocused = null;
  if (back) goTo(radar, back);
}

// A view's distance, held between the closest and the widest.
function zoomed(radar, nm) {
  return Math.min(Math.max(VIEW_MAX_NM, radar.range()), Math.max(VIEW_MIN_NM, nm));
}

// -- pointing, panning, zooming, focusing --

// The pointer in canvas pixels. The ratio is size()'s, which carries any
// render scale, as every pointer and hit reckoning here does.
function local(radar, event) {
  const { ratio } = radar.size();
  const box = radar.canvas.getBoundingClientRect();
  return [(event.clientX - box.left) * ratio, (event.clientY - box.top) * ratio];
}

const inside = (r, x, y) => Boolean(r) && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;

// The aircraft with tags, the tag on top first. The traffic says which
// order it laid its tags in (`radar.tagOrder`, the one on top last); a tag
// it does not name is under those it does, and with no order said the
// frame's order (`radar.hits`) is the one.
function tagsTopFirst(radar) {
  const tagged = radar.hits.filter((hit) => hit.tag);
  const order = radar.tagOrder;
  if (!order || !order.length) return tagged;
  const at = new Map(order.map((hex, i) => [hex, i]));
  const height = (hit) => (at.has(hit.hex) ? at.get(hit.hex) : -1);
  return tagged.sort((a, b) => height(b) - height(a)); // stable: the rest keep the frame's order
}

// The aircraft drawn on top where the pointer is. A chevron is over its
// trail and every other's, and over a tag drawn without a box. Once the
// tags are a layer of their own over the aircraft (the traffic then says
// their order, `radar.tagOrder`), a tag's filled box hides the chevrons
// under it: where one is, the tag on top there is the one pointed at.
function hitAircraft(radar, [x, y]) {
  const { ratio } = radar.size();
  const tagged = tagsTopFirst(radar).filter((hit) => inside(hit.tag, x, y));
  const covered = Array.isArray(radar.tagOrder) && radar.store.state.prefs.box_fill > 0
    && tagged.some((hit) => hit.tag.boxed && inside(hit.tag.box, x, y));
  if (covered) return tagged[0].hex;
  for (const hit of radar.hits) {
    if (Math.hypot(hit.x - x, hit.y - y) < 14 * ratio) return hit.hex;
  }
  if (tagged.length) return tagged[0].hex;
  for (const hit of radar.hits) {
    for (let i = 1; i < hit.trail.length; i += 1) {
      if (nearSegment(x, y, hit.trail[i - 1], hit.trail[i]) < 6 * ratio) return hit.hex;
    }
  }
  return null;
}

// The place where the pointer is (phase G decision 12): a label first, then
// the nearest symbol within its reach, the home ring's being the ring.
// { key, xy } or null. Lines are not places.
function hitPlace(radar, [x, y]) {
  const label = radar.placed.find((p) => p.xy && inside(p, x, y));
  if (label) return label;
  let best = null;
  let nearest = Infinity;
  for (const mark of radar.marks) {
    const d = Math.hypot(mark.point[0] - x, mark.point[1] - y);
    if (d <= mark.reach && d < nearest) { best = mark; nearest = d; }
  }
  return best;
}

function positionText(radar, at) {
  const { view } = radar;
  const { ratio, width, height } = radar.size();
  const s = scale(radar, width, height, ratio);
  const x = view.panX + (at[0] - width / 2) / s;
  const y = view.panY + (at[1] - height / 2) / s;
  const nm = Math.hypot(x, y);
  const brg = (Math.round((Math.atan2(x, -y) * 180) / Math.PI) + 360) % 360;
  return `${String(brg).padStart(3, "0")}° ${nm.toFixed(1)} NM`;
}

// The canvas's pointer, wheel and double click handlers.
function bindPointer(radar) {
  const { canvas, view, pointer, hud } = radar;

  canvas.addEventListener("pointerdown", (event) => {
    pointer.at = local(radar, event);
    pointer.down = { at: pointer.at, panX: view.panX, panY: view.panY };
    pointer.before = pointer.moved;
    pointer.moved = false;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const at = local(radar, event);
    pointer.at = at;
    if (pointer.down) {
      const { ratio, width, height } = radar.size();
      const s = scale(radar, width, height, ratio);
      const dx = at[0] - pointer.down.at[0];
      const dy = at[1] - pointer.down.at[1];
      if (!pointer.moved && Math.hypot(dx, dy) > 4 * ratio) {
        // A drag: from the view as it is now, which a move or the
        // following may have taken on since the press.
        pointer.moved = true;
        radar.ease = null;
        radar.following = false;
        pointer.down.panX = view.panX;
        pointer.down.panY = view.panY;
      }
      if (pointer.moved) {
        view.panX = pointer.down.panX - dx / s;
        view.panY = pointer.down.panY - dy / s;
        radar.staticDirty = true;
      }
      return;
    }
    const over = radar.placed.find((p) => at[0] >= p.x && at[0] <= p.x + p.w && at[1] >= p.y && at[1] <= p.y + p.h);
    const key = over ? over.key : null;
    if (key !== radar.hovered) { radar.hovered = key; radar.staticDirty = true; }
    canvas.style.cursor = hitAircraft(radar, at) || hitPlace(radar, at) ? "pointer" : pointer.down ? "grabbing" : "crosshair";
    if (hud.position) hud.position.textContent = positionText(radar, at);
  });

  canvas.addEventListener("pointerup", (event) => {
    const at = local(radar, event);
    if (pointer.down && !pointer.moved) {
      const hex = hitAircraft(radar, at);
      const place = hex ? null : hitPlace(radar, at);
      if (hex) {
        focus.toggle(hex);
      } else if (place) {
        // Centred, at the same zoom, and no longer following.
        radar.following = false;
        goTo(radar, { nm: view.nm, x: place.xy[0], y: place.xy[1] });
      }
    }
    pointer.down = null;
  });

  canvas.addEventListener("pointerleave", () => {
    if (radar.hovered) { radar.hovered = null; radar.staticDirty = true; }
    if (hud.position) hud.position.textContent = "";
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const { ratio, width, height } = radar.size();
    const factor = Math.exp(-event.deltaY * WHEEL_RATE * (radar.store.state.prefs.zoom_speed / 100));
    if (radar.following) {
      // About the aircraft, which stays where it is: in the middle, or on
      // its way there.
      const { ease } = radar;
      if (ease) { ease.from.nm = zoomed(radar, ease.from.nm / factor); ease.to.nm = zoomed(radar, ease.to.nm / factor); }
      view.nm = zoomed(radar, view.nm / factor);
      radar.staticDirty = true;
      return;
    }
    radar.ease = null; // a wheel during a move ends it
    const at = local(radar, event);
    const before = scale(radar, width, height, ratio);
    view.nm = zoomed(radar, view.nm / factor);
    const after = scale(radar, width, height, ratio);
    // Keep the point under the pointer where it is.
    const nx = view.panX + (at[0] - width / 2) / before;
    const ny = view.panY + (at[1] - height / 2) / before;
    view.panX = nx - (at[0] - width / 2) / after;
    view.panY = ny - (at[1] - height / 2) / after;
    radar.staticDirty = true;
  }, { passive: false });

  // With no button for it, a double click is the way back from a pan. The
  // browser counts presses, not clicks: two quick pans from one spot, or a
  // click straight after a pan, also arrive as a double click and are not one.
  canvas.addEventListener("dblclick", (event) => {
    if (pointer.moved || pointer.before) return;
    recentre(radar);
    // The readout is for the view on screen, and the pointer has not moved.
    if (hud.position) hud.position.textContent = positionText(radar, local(radar, event));
  });
}

function nearSegment(x, y, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
