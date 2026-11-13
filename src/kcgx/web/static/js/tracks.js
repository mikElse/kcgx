// The tracks table under the radar (spec, Radar; phase G Task 8). Its columns
// are prefs.track_cols, in the schema's order, chosen from the COLUMNS
// checklist in the pane's title bar; its order is prefs.track_sort and
// track_desc, set by clicking a header, so every tab sorts alike. A row of
// filters under the header hides rows in this tab alone, until a reload:
// they are the page's, not settings (phase G decision 4).
//
// The first cell of a row is a button that focuses the aircraft, exactly as
// clicking it on the radar does; the focused row is pink, outlined, set
// larger, leads the table whatever the filters say, and the rest dim.
//
// The sort, with no filter applied and the focus first, also ranks every
// aircraft for the radar: store.state.rank, hex -> 0 for the first to 1 for
// the last, and a "rank" event when it changes (decision 5, Task 13).
//
// The pane itself is dragged taller or shorter by its top edge and folds to
// its title bar (Task 9): mountPane, at the end.

import { COLUMNS, COLUMN } from "./columns.js";
import { focus } from "./focus.js";

const EMERGENCY = new Set(["7500", "7600", "7700"]);

// UI zoom (prefs ui_zoom) is CSS zoom on .page, and the engines measure
// what is under it differently: getBoundingClientRect is in the window's px
// in Chromium and in the element's own px in WebKit. offsetWidth and the
// like, a length set in a style, and a pointer's clientY are the same in
// both: the element's own px, its own, and the window's.
//
// The window's px to one of the element's own: the product of every zoom
// from the element up.
function zoomOf(el) {
  let k = 1;
  for (let e = el; e; e = e.parentElement) k *= parseFloat(getComputedStyle(e).zoom) || 1;
  return k;
}

// An element's box in the window's px, in either engine. Whether its rect is
// zoomed is read from the rect against offsetWidth, and settled to one or the
// other, as offsetWidth is rounded.
function windowBox(el) {
  const r = el.getBoundingClientRect();
  const k = zoomOf(el);
  const s = el.offsetWidth ? r.width / el.offsetWidth : 1;
  const f = Math.abs(s - k) < Math.abs(s - 1) ? 1 : k;
  return { left: r.left * f, top: r.top * f, right: r.right * f, bottom: r.bottom * f, width: r.width * f, height: r.height * f };
}

// What a number filter's box says: no bound when empty, GND as 0, and NaN
// for anything that is not a figure (no bound either, and marked invalid).
function bound(text) {
  const word = text.trim().toUpperCase();
  if (!word) return null;
  if (word === "GND") return 0;
  const figure = Number(word);
  return Number.isFinite(figure) ? figure : NaN;
}

export function mountTracks({ head, filters, body, empty, columns, openColumns, clear }, store, send) {
  const { state } = store;
  let pressedHere = false; // true while a button in this table is being pressed
  let shown = []; // the columns shown, as the header was last built
  let builtFor = ""; // the track_cols the header was built for
  // The filters, by column: { text } or { min, max }, as typed.
  const typed = new Map();
  // A choice asked of the server and not yet answered: the next click
  // builds on it, as the config sheet's subset buttons do (sheets.js).
  let askedCols = null;
  let askedSort = null;

  const visible = () => {
    const names = state.prefs.track_cols || [];
    const picked = COLUMNS.filter((column) => names.includes(column.key));
    // The config sheet can send an empty list; the table keeps a column to click.
    return picked.length ? picked : [COLUMN.CALLSIGN];
  };

  // -- the header and the filter row --

  // The title bar names a sort the header cannot show: a hidden column's.
  const sortNote = document.createElement("span");
  sortNote.id = "tracks-sort";
  sortNote.className = "muted small tracks-sort";
  sortNote.hidden = true;
  clear.before(sortNote);

  function buildHead() {
    // A box being typed in is built again with the row: it keeps the focus
    // and the caret (another tab may change the columns at any moment).
    const typing = filters.contains(document.activeElement) ? document.activeElement : null;
    const caret = typing && [typing.dataset.key, typing.dataset.bound, typing.selectionStart, typing.selectionEnd];
    shown = visible();
    builtFor = String(state.prefs.track_cols);
    for (const key of [...typed.keys()]) if (!shown.some((column) => column.key === key)) typed.delete(key);
    head.replaceChildren(...shown.map((column) => {
      const th = document.createElement("th");
      if (column.num) th.className = "num";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sort";
      button.textContent = column.title;
      button.dataset.key = column.key;
      th.append(button);
      return th;
    }));
    // Cells, not headers: a screen reader would read a filter row of th as
    // the header of every cell below it. Each box has its own label.
    filters.replaceChildren(...shown.map((column) => {
      const td = document.createElement("td");
      td.className = column.filter;
      const now = typed.get(column.key) || {};
      const box = (bound, label, placeholder) => {
        const input = document.createElement("input");
        input.type = "text";
        input.spellcheck = false;
        input.autocomplete = "off";
        input.dataset.key = column.key;
        if (bound) {
          input.dataset.bound = bound;
          input.inputMode = "decimal";
        }
        input.placeholder = placeholder;
        input.value = now[bound || "text"] || "";
        input.setAttribute("aria-label", label);
        return input;
      };
      if (column.filter === "number") {
        td.append(box("min", `${column.title} at least`, "MIN"), box("max", `${column.title} at most`, "MAX"));
      } else {
        td.append(box(null, `${column.title} contains`, "FILTER"));
      }
      return td;
    }));
    if (caret) {
      const [key, which, start, end] = caret;
      const again = [...filters.querySelectorAll("input")]
        .find((input) => input.dataset.key === key && input.dataset.bound === which);
      if (again) {
        again.focus({ preventScroll: true });
        again.setSelectionRange(start, end);
      }
    }
    markInvalid();
    markSort();
  }

  function markSort() {
    const { track_sort: key, track_desc: desc } = state.prefs;
    for (const th of head.children) {
      const here = th.firstChild.dataset.key === key;
      th.setAttribute("aria-sort", here ? (desc ? "descending" : "ascending") : "none");
    }
    const column = COLUMN[key] || COLUMN.DIST; // as sorted() falls back
    sortNote.hidden = shown.includes(column);
    sortNote.textContent = `SORT ${column.title} ${desc ? "▼" : "▲"}`;
  }

  function markInvalid() {
    for (const input of filters.querySelectorAll("input[data-bound]")) {
      if (Number.isNaN(bound(input.value))) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    }
  }

  head.addEventListener("click", (event) => {
    const button = event.target.closest("button.sort");
    if (!button) return;
    const now = askedSort || { track_sort: state.prefs.track_sort, track_desc: state.prefs.track_desc };
    const key = button.dataset.key;
    askedSort = { track_sort: key, track_desc: key === now.track_sort ? !now.track_desc : false };
    send({ t: "prefs", ...askedSort });
  });

  filters.addEventListener("input", (event) => {
    const input = event.target;
    const key = input.dataset.key;
    const now = { ...(typed.get(key) || {}), [input.dataset.bound || "text"]: input.value };
    if (Object.values(now).some((text) => text.trim())) typed.set(key, now);
    else typed.delete(key);
    markInvalid();
    render();
  });

  clear.addEventListener("click", () => {
    typed.clear();
    for (const input of filters.querySelectorAll("input")) input.value = "";
    markInvalid();
    render();
  });

  // The filters as tests, one per column that has one.
  function tests() {
    const found = [];
    for (const [key, now] of typed) {
      const column = COLUMN[key];
      if (column.filter === "text") {
        const want = now.text.trim().toUpperCase();
        if (want) found.push((ac) => column.text(ac).toUpperCase().includes(want));
        continue;
      }
      const low = bound(now.min || "");
      const high = bound(now.max || "");
      const hasLow = low !== null && !Number.isNaN(low);
      const hasHigh = high !== null && !Number.isNaN(high);
      if (!hasLow && !hasHigh) continue;
      found.push((ac) => {
        const value = column.value(ac);
        return value !== null && (!hasLow || value >= low) && (!hasHigh || value <= high);
      });
    }
    return found;
  }

  // -- the checklist of columns --

  columns.replaceChildren(...COLUMNS.map((column) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn seg check";
    button.dataset.key = column.key;
    button.textContent = column.key;
    button.title = column.title;
    return button;
  }));

  // Marked as the table shows them: an empty track_cols shows the callsign.
  const shownKeys = () => visible().map((column) => column.key);

  function markColumns() {
    const names = shownKeys();
    for (const button of columns.children) {
      const on = names.includes(button.dataset.key);
      button.setAttribute("aria-pressed", String(on));
      // The last one shown stays: a table of no columns has nothing to click.
      button.disabled = on && names.length === 1;
    }
  }

  columns.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-key]");
    if (!button) return;
    const now = askedCols || shownKeys();
    const key = button.dataset.key;
    const next = COLUMNS.map((column) => column.key).filter((name) => (name === key) !== now.includes(name));
    if (!next.length) return;
    askedCols = next;
    send({ t: "prefs", track_cols: next });
  });

  // The checklist opens over the page, above its button, right edges level
  // (a popover: the pane clips what is inside it, the top layer does not);
  // below it when there is not the room above, and always on the screen.
  // It is in .page, so zoomed with it: placed in the window's px, then set
  // in its own (zoomOf).
  columns.addEventListener("beforetoggle", (event) => {
    if (event.newState !== "open") return;
    const k = zoomOf(columns);
    const across = document.documentElement.clientWidth;
    const down = window.innerHeight;
    columns.style.maxWidth = `${(across - 16) / k}px`;
    columns.style.maxHeight = `${(down - 16) / k}px`;
    // Not open yet, so not laid out: measured shown for a moment, unpainted.
    columns.style.display = "grid";
    const width = columns.offsetWidth * k;
    const height = columns.offsetHeight * k;
    columns.style.display = "";
    const at = windowBox(openColumns);
    const gap = 4 * k;
    const clamp = (value, size, room) => Math.max(8, Math.min(value, room - 8 - size));
    const above = at.top - gap - height;
    const top = clamp(above >= 8 ? above : at.bottom + gap, height, down);
    columns.style.left = `${clamp(at.right - width, width, across) / k}px`;
    columns.style.top = `${top / k}px`;
  });
  columns.addEventListener("toggle", (event) => {
    openColumns.setAttribute("aria-expanded", String(event.newState === "open"));
  });
  // Placed once, so closed when its button moves away or the window changes;
  // scrolling the checklist itself, or a scroller its button is not in, does not.
  const shut = () => { if (columns.matches(":popover-open")) columns.hidePopover(); };
  document.addEventListener("scroll", (event) => {
    const scrolled = event.target === document ? document.documentElement : event.target;
    if (scrolled.contains && scrolled.contains(openColumns)) shut();
  }, { capture: true, passive: true });
  window.addEventListener("resize", shut);

  // -- the rows --

  function sorted() {
    const radar = state.radar;
    const list = radar ? [...radar.ac] : [];
    const { track_sort: key, track_desc: desc } = state.prefs;
    const value = (COLUMN[key] || COLUMN.DIST).sort;
    const keyed = list.map((ac) => [value(ac), ac]);
    keyed.sort(([x, a], [y, b]) => {
      const order = x < y ? -1 : x > y ? 1 : a.hex < b.hex ? -1 : 1;
      return desc ? -order : order;
    });
    const ordered = keyed.map(([, ac]) => ac);
    // There is one focus, and it leads; the sort orders the rest.
    const at = ordered.findIndex((ac) => ac.hex === focus.hex);
    if (at > 0) ordered.unshift(...ordered.splice(at, 1));
    return ordered;
  }

  // The rank, changed in place (other modules hold the Map), and told only
  // when it changed.
  function publishRank(ordered) {
    const { rank } = state;
    const last = Math.max(1, ordered.length - 1);
    let changed = rank.size !== ordered.length;
    ordered.forEach((ac, i) => {
      const r = i / last;
      if (!changed && rank.get(ac.hex) !== r) changed = true;
    });
    if (!changed) return;
    rank.clear();
    ordered.forEach((ac, i) => rank.set(ac.hex, i / last));
    store.emit("rank");
  }

  function render() {
    const ordered = sorted();
    publishRank(ordered);
    const focused = focus.hex;
    const pass = tests();
    const list = pass.length ? ordered.filter((ac) => ac.hex === focused || pass.every((t) => t(ac))) : ordered;
    const rowsMade = list.map((ac) => {
      const tr = document.createElement("tr");
      tr.dataset.hex = ac.hex;
      if (EMERGENCY.has(ac.sq)) tr.classList.add("emergency");
      if (focused) tr.classList.add(ac.hex === focused ? "focused" : "dimmed");
      shown.forEach((column, i) => {
        const td = document.createElement("td");
        if (column.num) td.className = "num";
        const text = column.text(ac);
        if (i === 0) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "callsign";
          // Something to click when the column has nothing to say: the
          // callsign, muted, or a dash when there is not even that.
          if (text) button.textContent = text;
          else {
            button.textContent = COLUMN.CALLSIGN.text(ac) || "—";
            button.classList.add("stand-in");
          }
          button.setAttribute("aria-pressed", String(ac.hex === focused));
          button.setAttribute("aria-label", `Focus ${COLUMN.CALLSIGN.text(ac) || ac.hex.toUpperCase()} on the radar`);
          td.append(button);
        } else {
          td.textContent = text;
        }
        tr.append(td);
      });
      return tr;
    });
    body.replaceChildren(...rowsMade);
    clear.disabled = typed.size === 0;
    const radar = state.radar;
    empty.hidden = list.length > 0;
    empty.textContent = !radar || radar.age === null
      ? (radar && radar.error ? `THE RADAR IS NOT ANSWERING (${radar.error})` : "WAITING FOR THE RADAR")
      : ordered.length ? "NO TRAFFIC MATCHES THE FILTERS" : "NO TRAFFIC IN RANGE";
  }

  body.addEventListener("click", (event) => {
    const button = event.target.closest("button.callsign");
    if (!button) return;
    pressedHere = true;
    try { focus.toggle(button.closest("tr").dataset.hex); } finally { pressedHere = false; }
  });

  // Built again only for what changes it: traffic, the three settings the
  // table reads, the focus and the filters; never for levels or chatter.
  let sortedFor = "";
  store.subscribe((kind) => {
    if (kind === "all" || kind === "prefs") {
      const { track_cols: cols, track_sort: key, track_desc: desc } = state.prefs;
      if (kind === "all" || (askedCols && String(cols) === String(askedCols))) askedCols = null;
      if (kind === "all" || (askedSort && askedSort.track_sort === key && askedSort.track_desc === desc)) askedSort = null;
      markColumns();
      const sortNow = `${key} ${desc}`;
      const colsChanged = String(cols) !== builtFor;
      if (colsChanged) buildHead();
      else if (sortNow !== sortedFor) markSort();
      if (kind === "all" || colsChanged || sortNow !== sortedFor) {
        sortedFor = sortNow;
        render();
      }
    } else if (kind === "aircraft") {
      render();
    }
  });
  // The focused row is the first, so showing it is scrolling to the top.
  // In one column the page scrolls too, and the table's top may be off the
  // page: a callsign pressed here takes the page to its row. A click on the
  // radar does not, or the radar would be scrolled out of sight.
  const scroller = body.closest(".tracks-body");
  focus.subscribe((hex) => {
    render();
    if (!hex) return;
    if (scroller) scroller.scrollTop = 0;
    if (pressedHere && body.firstElementChild) body.firstElementChild.scrollIntoView({ block: "nearest" });
  });
  // The filter row sticks under the header, however tall the font makes it.
  // In the header's own px: a rect would be zoomed twice in Chromium.
  const table = head.closest("table");
  new ResizeObserver(() => {
    table.style.setProperty("--tracks-head-h", `${windowBox(head).height / zoomOf(head)}px`);
  }).observe(head);
  mountPane(head.closest(".screen-tracks"), store, send);
  buildHead();
  markColumns();
  sortedFor = `${state.prefs.track_sort} ${state.prefs.track_desc}`;
  render();
}

// -- the pane's height and its fold (phase G Task 9, decision 18) --
//
// The grip along the pane's top edge sets prefs.tracks_pct, the button in its
// title bar prefs.tracks_open; both are settings, so every tab follows. A
// drag shows here as it goes and is sent on release (Escape puts it back and
// sends nothing); nothing else changes the page before the server answers.
// What they set is --tracks-row on .page, the grid's last row: tracks_pct
// percent of the page's content box (the window's height, or the page's
// least, less its padding), the row being the pane and the gap above it; or,
// folded, as tall as the title bar.
//
// The drag and the keys stay between two ends, read from the page as it is
// laid out: at the most, what leaves the radar's own row its floor (the page
// does not scroll); at the least, 10 % or what shows the header, the filter
// row and two rows of the table, whichever is more. A percent set where the
// window was taller is held to the first by the grid itself (cockpit.css).

const PCT_LOW = 10;
const PCT_HIGH = 80;
const STEP = { ArrowUp: 2, ArrowDown: -2, PageUp: 10, PageDown: -10 }; // up for a taller pane, as dragging up makes it
const RADAR_ROW_LEAST = 48; // px: the radar's own row's floor, minmax(48px, 1fr) in cockpit.css's .page rule
const TABLE_ROWS_LEAST = 2; // rows of the table the pane always has room for

function mountPane(pane, store, send) {
  const { state } = store;
  const page = pane.closest(".page");
  const grip = pane.querySelector("#tracks-grip");
  const fold = pane.querySelector("#tracks-fold");
  const scroller = pane.querySelector("#tracks-scroll");
  const thead = scroller.querySelector("thead");
  const headRow = thead.querySelector("#tracks-head");
  const body = scroller.querySelector("#tracks-body");
  const log = page.querySelector(".screen-log .log");
  let drag = null; // { id, y, from, perPct, low, high, pct } while the grip is held
  let dropped = null; // the percent sent on release, shown until the server answers
  let askedPct = null; // the last a key asked for, for the next to build on
  let askedOpen = null; // as for the fold button
  let wasOpen = true;

  const pctNow = () => (drag ? drag.pct : dropped ?? state.prefs.tracks_pct);
  // What was given connection.js and not dropped (it drops all while the socket is closed).
  const sent = (message) => send(message) !== false;

  // The page as laid out now, in its own px (offsetHeight and the computed
  // tracks are in an element's own px in both engines, and the pane is in
  // the page's): its content box, the percent the row shows, and the ends.
  function measure() {
    const style = getComputedStyle(page);
    const content = page.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    const tracks = style.gridTemplateRows.split(" ").map(parseFloat);
    const row = tracks[tracks.length - 1];
    const radar = tracks[3]; // bar, banner, status, then the radar's own
    const most = ((row + Math.max(0, radar - RADAR_ROW_LEAST)) / content) * 100;
    // The pane less its scroller, and the scroller's padding, header, filters and rows.
    const pad = getComputedStyle(scroller);
    const tr = body.querySelector("tr:not(.focused)") || body.firstElementChild || headRow;
    const least = row - scroller.clientHeight + parseFloat(pad.paddingTop) + parseFloat(pad.paddingBottom)
      + thead.offsetHeight + TABLE_ROWS_LEAST * tr.offsetHeight;
    // Whole percents inside the ends (the setting is one), with a hair for rounding.
    const low = Math.max(PCT_LOW, Math.ceil((least / content) * 100 - 0.05));
    const high = Math.max(low, Math.min(PCT_HIGH, Math.floor(most + 0.05)));
    return { content, shown: (row / content) * 100, low, high };
  }

  function show() {
    const open = state.prefs.tracks_open !== false;
    const pct = pctNow();
    page.style.setProperty("--tracks-row", open ? `minmax(0, ${pct}%)` : "min-content");
    page.dataset.tracks = open ? "open" : "folded";
    pane.classList.toggle("folded", !open);
    fold.setAttribute("aria-expanded", String(open));
    fold.title = open ? "FOLD" : "UNFOLD";
    grip.setAttribute("aria-valuenow", String(Math.round(pct)));
    // Folded, the teletype's lines are hidden, and a hidden scroller forgets
    // where it was: open again, it shows the last, as it would have.
    if (open && !wasOpen && log) log.scrollTop = log.scrollHeight;
    wasOpen = open;
  }

  // The pointer moves in the window's px; a percent is of the page's content
  // box, in its own px, which the page's zoom makes the window's. The drag
  // moves from what the row shows, which is less than the setting when the
  // setting is more than this window has room for.
  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || drag) return;
    event.preventDefault();
    const { content, shown, low, high } = measure();
    const pct = pctNow();
    const from = shown < pct - 0.5 ? shown : pct;
    drag = { id: event.pointerId, y: event.clientY, from, perPct: (content * zoomOf(page)) / 100, low, high, pct };
    grip.setPointerCapture(event.pointerId);
    grip.classList.add("dragging");
    document.addEventListener("keydown", escape, true);
  });
  // A style written per move; the browser lays it out, and the radar's
  // canvas follows, once a frame however many moves come in it.
  grip.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    drag.pct = Math.min(drag.high, Math.max(drag.low, drag.from + (drag.y - event.clientY) / drag.perPct));
    show();
  });
  function endDrag() {
    const { id } = drag;
    drag = null;
    grip.classList.remove("dragging");
    document.removeEventListener("keydown", escape, true);
    return id;
  }
  // Sent on release when it changed the setting. One that sends nothing
  // (the same percent, or the socket closed) shows the server's value, not
  // an earlier release's that the server may never answer.
  function release(event, keep) {
    if (!drag || event.pointerId !== drag.id) return;
    const pct = Math.round(drag.pct); // the setting is a whole percent
    endDrag();
    dropped = keep && pct !== state.prefs.tracks_pct && sent({ t: "prefs", tracks_pct: pct }) ? pct : null;
    if (dropped !== null) askedPct = null;
    show();
  }
  grip.addEventListener("pointerup", (event) => release(event, true));
  grip.addEventListener("lostpointercapture", (event) => release(event, true));
  grip.addEventListener("pointercancel", (event) => release(event, false));
  // Escape puts the pane back as it was before the drag, and lets the pointer go.
  function escape(event) {
    if (event.key !== "Escape" || !drag) return;
    event.preventDefault();
    event.stopPropagation();
    const id = endDrag();
    if (grip.hasPointerCapture(id)) grip.releasePointerCapture(id);
    show();
  }

  // Arrow keys by 2 %, Page Up and Down by 10, Home and End to the ends.
  grip.addEventListener("keydown", (event) => {
    if (drag || !(event.key in STEP || event.key === "Home" || event.key === "End")) return;
    event.preventDefault();
    const { low, high } = measure();
    const now = askedPct ?? pctNow();
    const next = event.key === "Home" ? low : event.key === "End" ? high
      : Math.min(high, Math.max(low, now + STEP[event.key]));
    if (next !== now && sent({ t: "prefs", tracks_pct: next })) {
      askedPct = next;
      return;
    }
    if (next !== now) askedPct = null;
    dropped = null;
    show();
  });

  fold.addEventListener("click", () => {
    askedOpen = !(askedOpen ?? state.prefs.tracks_open !== false);
    send({ t: "prefs", tracks_open: askedOpen });
  });

  store.subscribe((kind) => {
    if (kind !== "all" && kind !== "prefs") return;
    const { tracks_pct: pct, tracks_open: open } = state.prefs;
    if (kind === "all" || dropped === pct) dropped = null;
    if (kind === "all" || askedPct === pct) askedPct = null;
    if (kind === "all" || askedOpen === open) askedOpen = null;
    show();
  });
  show();
}
