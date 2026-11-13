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

import { COLUMNS, COLUMN } from "./columns.js";
import { focus } from "./focus.js";

const EMERGENCY = new Set(["7500", "7600", "7700"]);

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
  columns.addEventListener("beforetoggle", (event) => {
    if (event.newState !== "open") return;
    // Not open yet, so not laid out: measured shown for a moment, unpainted.
    columns.style.display = "grid";
    const { width, height } = columns.getBoundingClientRect();
    columns.style.display = "";
    const at = openColumns.getBoundingClientRect();
    const across = document.documentElement.clientWidth;
    const down = window.innerHeight;
    const clamp = (value, size, room) => Math.max(8, Math.min(value, room - 8 - size));
    const above = at.top - 4 - height;
    const top = clamp(above >= 8 ? above : at.bottom + 4, height, down);
    columns.style.left = `${clamp(at.right - width, width, across)}px`;
    columns.style.top = `${top}px`;
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
  const table = head.closest("table");
  new ResizeObserver(() => {
    table.style.setProperty("--tracks-head-h", `${head.getBoundingClientRect().height}px`);
  }).observe(head);
  buildHead();
  markColumns();
  sortedFor = `${state.prefs.track_sort} ${state.prefs.track_desc}`;
  render();
}
