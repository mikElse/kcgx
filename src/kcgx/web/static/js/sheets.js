// The three sheets: change airport, config and shut down. Each is a
// <dialog>, so focus, Escape and the backdrop come from the browser. The
// one exception is Escape in the airport search, which the browsers do not
// agree on; see mountAirportSheet. Also the master volume, which the config
// sheet held until phase G and the frequencies pane holds now.

function button(className, label, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = label;
  node.addEventListener("click", onClick);
  return node;
}

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status}`);
  return body;
}

export function mountAirportSheet({ sheet, query, results }, store, log) {
  let ask = 0;
  const search = debounce(async () => {
    const mine = (ask += 1);
    const q = query.value.trim();
    if (!q) { results.replaceChildren(); return; }
    let found = [];
    try { found = await json(`/api/airports?q=${encodeURIComponent(q)}`); } catch (error) { log.say(`airport search failed: ${error.message}`); }
    if (mine !== ask) return;
    if (!found.length) {
      const none = document.createElement("p");
      none.className = "muted small";
      none.textContent = "NO MATCHING AIRPORTS";
      results.replaceChildren(none);
      return;
    }
    results.replaceChildren(...found.slice(0, 40).map((airport) => {
      const node = button("choice", "", () => choose(airport.icao));
      const code = document.createElement("span");
      code.className = "code";
      code.textContent = airport.icao;
      const name = document.createElement("span");
      name.className = "what";
      name.textContent = airport.name.toUpperCase();
      const where = document.createElement("span");
      where.className = "muted small";
      where.textContent = airport.where.toUpperCase();
      if (store.state.airport && airport.icao === store.state.airport.icao) node.classList.add("current");
      node.append(code, name, where);
      return node;
    }));
  }, 150);

  async function choose(icao) {
    sheet.close();
    try {
      await json("/api/airport", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ icao }),
      });
    } catch (error) {
      log.say(`could not change airport: ${error.message}`);
    }
  }

  query.addEventListener("input", search);
  // Escape closes the sheet, typed query or none. Left to the browser, a
  // search field with text in it takes the key for itself in Chromium (it
  // empties the field, and the sheet stays), and not in WebKit.
  query.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.isComposing) return;
    event.preventDefault();
    sheet.close();
  });
  return {
    // `text` prefills the search: `kcgx go seattle` opens the page this way.
    open(text = "") {
      query.value = text;
      results.replaceChildren();
      if (!sheet.open) sheet.showModal();
      query.focus();
      if (text) search();
    },
  };
}

// -- config ---------------------------------------------------------------------
//
// Every setting is a [data-pref] control declared in index.html, with its
// range or its names in the markup. Nothing here knows a setting by name:
// a control is bound by what it is, sends a `prefs` message, and is drawn
// from the server's answer. Each binder returns how to draw its value.

const SLIDER_MS = 80; // a drag sends where it paused, not every step

const words = (text) => (text || "").split(/\s+/).filter(Boolean);

function bindSelect(node, set) {
  node.addEventListener("change", () => set(node.value));
  return (value) => { node.value = value; };
}

// What a slider's readout says: "40%", "12 PX", and with data-scale="10"
// (a setting kept in tenths) "1.8 PX".
function readoutText(readout, value) {
  const { unit, scale } = readout.dataset;
  const shown = scale ? (Number(value) / Number(scale)).toFixed(1) : value;
  return unit === "%" ? `${shown}%` : `${shown} ${unit}`;
}

// A slider shows what it is dragged to at once and sends it a moment
// later. While it is in hand (focused, or with a send still to go) a frame
// from the server does not move it, as the volume slider is not moved.
function bindSlider(node, set, redraw) {
  const readout = node.parentElement.querySelector("[data-unit]");
  const show = (value) => { if (readout) readout.textContent = readoutText(readout, value); };
  let timer = 0;
  node.addEventListener("input", () => {
    show(node.value);
    clearTimeout(timer);
    timer = setTimeout(() => { timer = 0; set(Math.round(Number(node.value))); }, SLIDER_MS);
  });
  node.addEventListener("blur", redraw);
  return (value) => {
    if (timer || document.activeElement === node) return;
    node.value = String(value);
    show(value); // the setting, which a slider's step may not be able to show
  };
}

// A row of buttons, each [label, value]; `lit(value, setting)` says which are pressed.
function bindSegments(node, options, onClick, lit) {
  node.replaceChildren(...options.map(([label, value]) => button("btn seg", label, () => onClick(value))));
  return (setting) => {
    options.forEach(([, value], i) => node.children[i].setAttribute("aria-pressed", String(lit(value, setting))));
  };
}

// One control, of any kind but a table: `set(value)` sends the setting,
// `current()` is what the server last said it is.
function bindControl(node, store, set, current, redraw) {
  if (node.tagName === "SELECT") return bindSelect(node, set);
  if (node.tagName === "INPUT") return bindSlider(node, set, redraw);
  const names = words(node.dataset.values).map((name) => [name, name]);
  switch (node.dataset.kind) {
    case "flag": // OFF or ON
      return bindSegments(node, [["OFF", false], ["ON", true]], set, (value, setting) => value === Boolean(setting));
    case "subset": { // each button is its own switch; the whole list is sent, in the declared order
      // The store holds only what the server has said, so a second press
      // made before the first is answered would send a list without it. A
      // press builds on the list last asked for until a frame shows that
      // list. A snapshot is the server's whole word (the first frame after
      // a reconnect is one), so nothing asked for outlives it.
      let asked = null;
      store.subscribe((kind) => {
        const answered = kind === "prefs" && asked && String(current()) === String(asked);
        if (kind === "all" || answered) asked = null;
      });
      return bindSegments(node, names, (name) => {
        const now = asked || current() || [];
        asked = names.map(([n]) => n).filter((n) => (n === name) !== now.includes(n));
        set(asked);
      }, (value, setting) => (setting || []).includes(value));
    }
    default: // a choice: one pressed button
      return bindSegments(node, names, set, (value, setting) => value === setting);
  }
}

// A cell's control, made from its column's heading: a slider and its
// readout for a number, a row of buttons for a flag or a choice.
function cellControl(heading, label) {
  const { kind, values, min, max, step, unit, scale } = heading.dataset;
  if (kind === "number") {
    const input = Object.assign(document.createElement("input"), { type: "range", min, max, step: step || "1" });
    input.setAttribute("aria-label", label);
    const readout = document.createElement("span");
    readout.className = "num";
    readout.dataset.unit = unit;
    if (scale) readout.dataset.scale = scale;
    return [input, readout];
  }
  const group = document.createElement("div");
  group.className = "segments";
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", label);
  group.dataset.kind = kind;
  if (values) group.dataset.values = values;
  return [group];
}

// A table (the map's layers): a row per data-rows entry, "ROW:col,col", and
// a column per heading. A cell is made only where its row has that column,
// and is bound as a control of its own that sends only itself:
// {t: "prefs", key: {ROW: {col: value}}}. The server merges it cell by cell.
function bindTable(table, store, send, redraw) {
  const key = table.dataset.pref;
  const headings = [...table.tHead.querySelectorAll("th[data-column]")];
  const cells = [];
  table.tBodies[0].replaceChildren(...words(table.dataset.rows).map((item) => {
    const [row, list = ""] = item.split(":");
    const has = list.split(",");
    const tr = document.createElement("tr");
    tr.dataset.row = row;
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = row.replaceAll("_", " ");
    tr.append(name);
    for (const heading of headings) {
      const column = heading.dataset.column;
      const td = document.createElement("td");
      tr.append(td);
      if (!has.includes(column)) continue;
      td.dataset.row = row;
      td.dataset.column = column;
      const parts = cellControl(heading, `${name.textContent} ${heading.textContent}`);
      td.append(...parts);
      const draw = bindControl(
        parts[0], store,
        (value) => send({ t: "prefs", [key]: { [row]: { [column]: value } } }),
        () => store.state.prefs[key]?.[row]?.[column],
        redraw,
      );
      cells.push({ row, column, draw });
    }
    return tr;
  }));
  return (value) => { for (const { row, column, draw } of cells) draw(value?.[row]?.[column]); };
}

function bind(node, store, send, redraw) {
  if (node.dataset.kind === "table") return bindTable(node, store, send, redraw);
  const key = node.dataset.pref;
  return bindControl(node, store, (value) => send({ t: "prefs", [key]: value }), () => store.state.prefs[key], redraw);
}

// The tabs: buttons over panels, one shown. A click or the arrow keys (and
// Home and End) pick one; only the picked tab is in the Tab order. The
// sheet reopens on the last one picked, for as long as the page is open.
function mountTabs(sheet) {
  const tabs = [...sheet.querySelectorAll("[role=tab]")];
  const panel = (tab) => document.getElementById(tab.getAttribute("aria-controls"));
  function pick(chosen) {
    for (const tab of tabs) {
      const on = tab === chosen;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      panel(tab).hidden = !on;
    }
  }
  for (const tab of tabs) tab.addEventListener("click", () => pick(tab));
  sheet.querySelector("[role=tablist]").addEventListener("keydown", (event) => {
    const at = tabs.indexOf(document.activeElement);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[event.key];
    if (at < 0 || to === undefined) return;
    event.preventDefault();
    const chosen = tabs[(to + tabs.length) % tabs.length];
    pick(chosen);
    chosen.focus();
  });
  pick(tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0]);
}

export function mountConfigSheet({ sheet }, store, send) {
  mountTabs(sheet);
  const controls = [...sheet.querySelectorAll("[data-pref]")].map((node) => {
    // data-only-when="display=CRT": the control works only with that setting so.
    const [needs, needed] = (node.dataset.onlyWhen || "").split("=");
    return { node, key: node.dataset.pref, needs, needed, draw: bind(node, store, send, () => render()) };
  });

  function render() {
    const { state } = store;
    for (const { node, key, needs, needed, draw } of controls) {
      draw(state.prefs[key]);
      if (!needs) continue;
      const off = state.prefs[needs] !== needed;
      for (const part of node.matches("input, select") ? [node] : node.children) part.disabled = off;
      node.closest(".field-row").classList.toggle("off", off);
    }
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "prefs") render(); });
  render();
  return { open() { render(); if (!sheet.open) sheet.showModal(); } };
}

// -- the master volume -------------------------------------------------------------
//
// Not a pref: it is the server's audio state, and lives in the frequencies
// pane, not the config sheet (phase G decision 3). Like a slider in the
// sheet, a frame from the server does not move it while it has the focus.

export function mountVolume({ volume, volumeValue }, store, send) {
  const sendVolume = debounce((value) => send({ t: "volume", value }), 60);
  volume.addEventListener("input", () => {
    volumeValue.textContent = `${volume.value}%`;
    sendVolume(Number(volume.value) / 100);
  });
  function render() {
    if (document.activeElement === volume) return;
    volume.value = String(Math.round(store.state.volume * 100));
    volumeValue.textContent = `${volume.value}%`;
  }
  store.subscribe((kind) => { if (kind === "all" || kind === "volume") render(); });
  render();
}

export function mountShutdownSheet({ sheet }, store, onEnded, log) {
  sheet.addEventListener("close", async () => {
    if (sheet.returnValue !== "confirm") return;
    try {
      await json("/api/shutdown", { method: "POST" });
      onEnded();
    } catch (error) {
      log.say(`shut down failed: ${error.message}`);
    }
  });
  return { open() { sheet.returnValue = ""; sheet.showModal(); } };
}
