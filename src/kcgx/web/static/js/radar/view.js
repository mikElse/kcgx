// The view and the pointer: where the radar looks (`radar.view`, held in
// nautical miles), how screen pixels map to it, and what the pointer does
// to it: drag to pan, wheel to zoom about the pointer, double click to
// recentre, click an aircraft to focus it, hover a label to brighten it,
// and the bearing and distance under the pointer.
//
// `radar` is the shared state `mountRadar` makes (see radar/index.js).

import { focus } from "../focus.js";

const VIEW_MIN_NM = 2.5; // the closest view: this far from the centre to the nearer edge
const VIEW_MAX_NM = 160; // the widest, or the range if that is wider
const EDGE_PX = 18; // kept clear between the view's distance and the nearer edge

// The range is a setting (prefs.range_nm). The view is held in nautical
// miles: `nm` from the centre to the nearer edge, less EDGE_PX. It starts
// at the range and returns to it; pan is in nm too.
export function newView(range) {
  return { nm: range, panX: 0, panY: 0 };
}

// Pixels per nm: the view's distance fits the shorter side.
export function scale(radar, width, height, ratio) {
  return Math.max(0, Math.min(width, height) / 2 - EDGE_PX * ratio) / radar.view.nm;
}

export function toScreen(radar, xy, s, width, height) {
  const { view } = radar;
  return [width / 2 + (xy[0] - view.panX) * s, height / 2 + (xy[1] - view.panY) * s];
}

// Back to the whole range, about the airport. A drag that is under way
// (the range or the airport can change beneath one) carries on from here.
export function recentre(radar) {
  const { view, pointer } = radar;
  view.nm = radar.range();
  view.panX = 0;
  view.panY = 0;
  radar.viewFor = view.nm;
  if (pointer.down) pointer.down = { at: pointer.at, panX: 0, panY: 0 };
  radar.staticDirty = true;
}

// -- pointing, panning, zooming, focusing --

function local(canvas, event) {
  const ratio = window.devicePixelRatio || 1;
  const box = canvas.getBoundingClientRect();
  return [(event.clientX - box.left) * ratio, (event.clientY - box.top) * ratio];
}

// An aircraft is its chevron before it is anything else: one that lies
// under another's tag or trail is still the one pointed at.
function hitAircraft(radar, [x, y]) {
  const ratio = window.devicePixelRatio || 1;
  for (const hit of radar.hits) {
    if (Math.hypot(hit.x - x, hit.y - y) < 14 * ratio) return hit.hex;
  }
  for (const hit of radar.hits) {
    const l = hit.tag;
    if (l && x >= l.x && x <= l.x + l.w && y >= l.y && y <= l.y + l.h) return hit.hex;
    for (let i = 1; i < hit.trail.length; i += 1) {
      if (nearSegment(x, y, hit.trail[i - 1], hit.trail[i]) < 6 * ratio) return hit.hex;
    }
  }
  return null;
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
export function bindPointer(radar) {
  const { canvas, view, pointer, hud } = radar;

  canvas.addEventListener("pointerdown", (event) => {
    pointer.at = local(canvas, event);
    pointer.down = { at: pointer.at, panX: view.panX, panY: view.panY };
    pointer.before = pointer.moved;
    pointer.moved = false;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const at = local(canvas, event);
    pointer.at = at;
    if (pointer.down) {
      const { ratio, width, height } = radar.size();
      const s = scale(radar, width, height, ratio);
      const dx = at[0] - pointer.down.at[0];
      const dy = at[1] - pointer.down.at[1];
      if (Math.hypot(dx, dy) > 4 * ratio) pointer.moved = true;
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
    canvas.style.cursor = hitAircraft(radar, at) ? "pointer" : pointer.down ? "grabbing" : "crosshair";
    if (hud.position) hud.position.textContent = positionText(radar, at);
  });

  canvas.addEventListener("pointerup", (event) => {
    const at = local(canvas, event);
    if (pointer.down && !pointer.moved) {
      const hex = hitAircraft(radar, at);
      if (hex) focus.toggle(hex);
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
    const at = local(canvas, event);
    const before = scale(radar, width, height, ratio);
    const factor = Math.exp(-event.deltaY * 0.0015);
    view.nm = Math.min(Math.max(VIEW_MAX_NM, radar.range()), Math.max(VIEW_MIN_NM, view.nm / factor));
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
    if (hud.position) hud.position.textContent = positionText(radar, local(canvas, event));
  });
}

function nearSegment(x, y, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
