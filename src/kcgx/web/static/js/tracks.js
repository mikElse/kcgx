// The tracks table under the radar (spec, Radar): callsign, type, altitude,
// ground speed, track, distance and squawk, sortable by any column. The
// callsign is a button that focuses the aircraft, exactly as clicking it on
// the radar does; the focused row is pink, outlined, set larger and moved to
// the top of the table, and the rest dim.

import { focus } from "./focus.js";

const EMERGENCY = new Set(["7500", "7600", "7700"]);
const COLUMNS = [
  { key: "label", title: "CALLSIGN", text: (a) => a.label },
  { key: "type", title: "TYPE", text: (a) => a.type || "" },
  { key: "alt", title: "ALT FT", num: true, text: (a) => (a.alt === null ? "" : String(a.alt)), sort: (a) => (a.alt === "GND" ? 0 : a.alt ?? -1) },
  { key: "gs", title: "GS KT", num: true, text: (a) => (a.gs === null ? "" : String(a.gs)), sort: (a) => a.gs ?? -1 },
  { key: "trk", title: "TRK", num: true, text: (a) => (a.trk === null ? "" : String(a.trk).padStart(3, "0")), sort: (a) => a.trk ?? -1 },
  { key: "dist", title: "DIST NM", num: true, text: (a) => a.dist.toFixed(1), sort: (a) => a.dist },
  { key: "sq", title: "SQWK", num: true, text: (a) => a.sq || "" },
];

export function mountTracks({ head, body, empty }, store) {
  let sortKey = "dist";
  let ascending = true;
  let pressedHere = false;  // true while a callsign in this table is being pressed

  head.replaceChildren(...COLUMNS.map((column) => {
    const th = document.createElement("th");
    if (column.num) th.className = "num";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort";
    button.textContent = column.title;
    button.dataset.key = column.key;
    button.addEventListener("click", () => {
      if (sortKey === column.key) ascending = !ascending;
      else { sortKey = column.key; ascending = true; }
      render();
    });
    th.append(button);
    return th;
  }));

  function render() {
    const radar = store.state.radar;
    const list = radar ? [...radar.ac] : [];
    const column = COLUMNS.find((c) => c.key === sortKey);
    const value = column.sort || column.text;
    list.sort((a, b) => {
      const x = value(a);
      const y = value(b);
      const order = x < y ? -1 : x > y ? 1 : a.hex < b.hex ? -1 : 1;
      return ascending ? order : -order;
    });
    for (const th of head.querySelectorAll("th")) {
      const key = th.firstChild.dataset.key;
      th.setAttribute("aria-sort", key === sortKey ? (ascending ? "ascending" : "descending") : "none");
    }
    // There is one focus, and it leads the table; sorting orders the rest.
    const focused = focus.hex;
    const at = list.findIndex((ac) => ac.hex === focused);
    if (at > 0) list.unshift(...list.splice(at, 1));
    body.replaceChildren(...list.map((ac) => {
      const tr = document.createElement("tr");
      tr.dataset.hex = ac.hex;
      if (EMERGENCY.has(ac.sq)) tr.classList.add("emergency");
      if (focused) tr.classList.add(ac.hex === focused ? "focused" : "dimmed");
      COLUMNS.forEach((c, i) => {
        const td = document.createElement("td");
        if (c.num) td.className = "num";
        if (i === 0) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "callsign";
          button.textContent = c.text(ac);
          button.setAttribute("aria-pressed", String(ac.hex === focused));
          button.setAttribute("aria-label", `Focus ${c.text(ac)} on the radar`);
          button.addEventListener("click", () => {
            pressedHere = true;
            try { focus.toggle(ac.hex); } finally { pressedHere = false; }
          });
          td.append(button);
        } else {
          td.textContent = c.text(ac);
        }
        tr.append(td);
      });
      return tr;
    }));
    empty.hidden = list.length > 0;
    empty.textContent = !radar || radar.age === null
      ? (radar && radar.error ? `THE RADAR IS NOT ANSWERING (${radar.error})` : "WAITING FOR THE RADAR")
      : "NO TRAFFIC IN RANGE";
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "aircraft") render(); });
  // The focused row is the first, so showing it is scrolling to the top.
  // In one column the table does not scroll, the page does, and its top may
  // be off the page: a callsign pressed here takes the page to its row. A
  // click on the radar does not, or the radar would be scrolled out of sight.
  const scroller = body.closest(".tracks-body");
  focus.subscribe((hex) => {
    render();
    if (!hex) return;
    if (scroller) scroller.scrollTop = 0;
    if (pressedHere && body.firstElementChild) body.firstElementChild.scrollIntoView({ block: "nearest" });
  });
  render();
}
