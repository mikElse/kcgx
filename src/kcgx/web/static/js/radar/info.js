// The focused aircraft's data box (phase G decision 11, Task 12): `#ac-info`,
// a <dl> over the radar with a `NAME: VALUE` line for each of the tracks
// table's visible columns (prefs.track_cols), in the table's order, read
// through the table's own columns (columns.js), so a value reads the same
// in each. It is a page element, not a drawing, so it is sharp at any
// render scale and in the page's font.
//
// It sits left of the chevron, its right edge GAP_PX clear of it and its
// middle level with it; where that would leave the radar, right of it and
// under the aircraft's tag, which is up and right. It is placed after every
// frame (view.js's `post`), from where that frame drew the aircraft, and
// hidden with prefs.info_box off, with nothing focused, and while the
// aircraft is off the screen. With AIRCRAFT among the boxed labels
// (prefs.box_items) it is boxed as the tags are (the stylesheet, from the
// same four settings main.js writes for the readouts).

import { COLUMN } from "../columns.js";
import { focus } from "../focus.js";

const REACH_PX = 9; // the chevron reaches this far from its point, whichever way it points
const GAP_PX = 12; // between the box and the chevron
const UNDER_PX = 12; // on the right, the box's top this far under the aircraft, clear of its tag

// The box's placer, for view.js to run after each frame: a function that
// does nothing when the page has no box.
export function mountInfo(radar) {
  const box = radar.canvas.parentElement ? radar.canvas.parentElement.querySelector("#ac-info") : null;
  if (!box) return () => {};
  let said = null; // what the box last said, to write it again only when it changes
  let size = [0, 0]; // its size in CSS px, measured when it was written
  // The page's font or size may change under it: measure it again.
  radar.store.subscribe((kind) => { if (kind === "all" || kind === "prefs") said = null; });

  const hide = () => {
    if (!box.hidden) box.hidden = true;
    said = null;
  };

  return function placeInfo() {
    const { prefs, radar: frame } = radar.store.state;
    const hex = focus.hex;
    if (!hex || !prefs.info_box || !frame) return hide();
    const hit = radar.hits.find((one) => one.hex === hex);
    const ac = frame.ac.find((one) => one.hex === hex);
    const { ratio, width, height } = radar.size();
    if (!hit || !ac || hit.x < 0 || hit.y < 0 || hit.x > width || hit.y > height) return hide();

    const boxed = radar.boxed("AIRCRAFT") ? "ON" : "OFF";
    const lines = prefs.track_cols.filter((name) => COLUMN[name]).map((name) => [COLUMN[name].title, COLUMN[name].text(ac)]);
    const says = JSON.stringify([boxed, lines]);
    if (box.hidden) box.hidden = false;
    if (says !== said) {
      box.dataset.boxed = boxed;
      box.replaceChildren(...lines.map(([name, value]) => {
        const line = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = name;
        dd.textContent = value;
        line.append(dt, dd);
        return line;
      }));
      said = says;
      size = [box.offsetWidth, box.offsetHeight];
    }

    // In the radar's CSS px.
    const x = hit.x / ratio;
    const y = hit.y / ratio;
    const [w, h] = size;
    let left = x - REACH_PX - GAP_PX - w;
    let top = y - h / 2;
    const right = left < 0;
    if (right) {
      left = x + REACH_PX + GAP_PX;
      top = y + UNDER_PX;
    }
    top = Math.max(0, Math.min(height / ratio - h, top));
    box.dataset.side = right ? "right" : "left";
    box.style.transform = `translate(${left}px, ${top}px)`;
  };
}
