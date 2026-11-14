// The two sheets, change airport and shut down, and the config panel. Each
// is a <dialog>. The sheets are modal, so focus, Escape and the backdrop
// come from the browser; the one exception is Escape in the airport search,
// which the browsers do not agree on (see mountAirportSheet). The config
// panel is not modal: it sits beside the cockpit (see mountConfigSheet).

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
// The config panel. Every setting is a [data-pref] control declared in
// index.html, with its names or its presets in the markup. Nothing here
// knows a setting by name: a control is bound by what it is, sends a
// `prefs` message, and is drawn from the server's answer. Each binder
// returns { keys, draw(prefs) } and, where the plain ones below will not do,
// its own changed(prefs, defaults) and reset(defaults).

const words = (text) => (text || "").split(/\s+/).filter(Boolean);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// data-values: "LABEL=value" each; a label's _ is a space, and a bare word
// is its own value.
function options(text) {
  return words(text).map((word) => {
    const [label, value = label] = word.split("=");
    return [label.replaceAll("_", " "), value];
  });
}

// "key=value,key=value": whether the settings are all so.
function holds(text, prefs) {
  return text.split(",").every((pair) => {
    const [key, value] = pair.split("=");
    return String(prefs[key]) === value;
  });
}

function bindSelect(node, key, set) {
  node.addEventListener("change", () => set({ [key]: node.value }));
  return { draw: (prefs) => { node.value = prefs[key]; } };
}

// A row of buttons, each [label, value]. `lit(value, prefs)` says which are
// pressed; `face(button, label, value)`, if given, draws one.
function bindButtons(node, className, list, onClick, lit, face) {
  node.replaceChildren(...list.map(([label, value]) => {
    const made = button(className, label, () => onClick(value));
    if (face) face(made, label, value);
    return made;
  }));
  return (prefs) => {
    list.forEach(([, value], i) => node.children[i].setAttribute("aria-pressed", String(lit(value, prefs))));
  };
}

// A mark before a button's words: the lamp of a switch, the box of a chip.
function mark(made) { made.prepend(document.createElement("i")); }

// One switch: a button that is pressed when on, and says ON or OFF. It is
// named by its row, as its own words change.
function bindSwitch(node, isOn, flip) {
  const made = button("btn tog", "", flip);
  const text = document.createTextNode("");
  made.append(document.createElement("i"), text);
  made.setAttribute("aria-label", node.closest("[aria-label]")?.getAttribute("aria-label") || "");
  node.replaceChildren(made);
  return (prefs) => {
    const on = isOn(prefs);
    made.setAttribute("aria-pressed", String(on));
    text.data = on ? "ON" : "OFF";
  };
}

// A theme's button: three bars in the theme's own colours over its wall,
// which the stylesheet's palettes give to anything with data-palette.
function swatch(made, label, value) {
  const art = document.createElement("span");
  art.className = "swatch-art";
  art.dataset.palette = value;
  art.setAttribute("aria-hidden", "true");
  art.append(...[0, 1, 2].map(() => document.createElement("span")));
  made.prepend(art);
}

// One control, of any kind but the layers: `set(changes)` sends settings,
// `current()` is what the server last said they are.
function bindControl(node, store, set, current) {
  const keys = words(node.dataset.pref);
  const [key] = keys;
  const list = options(node.dataset.values);
  if (node.tagName === "SELECT") return { keys, ...bindSelect(node, key, set) };
  switch (node.dataset.kind) {
    case "flag":
      return { keys, draw: bindSwitch(node, (prefs) => Boolean(prefs[key]), () => set({ [key]: !current()[key] })) };
    case "subset": { // each chip is its own switch; the whole list is sent, in the declared order
      // The store holds only what the server has said, so a second press
      // made before the first is answered would send a list without it. A
      // press builds on the list last asked for until a frame shows that
      // list. A snapshot is the server's whole word (the first frame after
      // a reconnect is one), so nothing asked for outlives it.
      let asked = null;
      store.subscribe((kind) => {
        const answered = kind === "prefs" && asked && String(current()[key]) === String(asked);
        if (kind === "all" || answered) asked = null;
      });
      return { keys, draw: bindButtons(node, "btn chip", list, (name) => {
        const now = asked || current()[key] || [];
        asked = list.map(([, n]) => n).filter((n) => (n === name) !== now.includes(n));
        set({ [key]: asked });
      }, (value, prefs) => (prefs[key] || []).includes(value), mark) };
    }
    case "preset": { // each button is a number for every key, or one number for each
      const changes = (value) => {
        const numbers = value.split(",").map(Number);
        return Object.fromEntries(keys.map((k, i) => [k, numbers[i] ?? numbers[0]]));
      };
      const is = (value, prefs) => Object.entries(changes(value)).every(([k, n]) => prefs[k] === n);
      if (node.dataset.look === "toggle") { // two presets as a switch: the first is off, the second on
        const [[, off], [, on]] = list;
        return { keys, draw: bindSwitch(node, (prefs) => is(on, prefs), () => set(changes(is(on, current()) ? off : on))) };
      }
      return { keys, draw: bindButtons(node, "btn seg", list, (value) => set(changes(value)), is) };
    }
    default: { // a choice: one pressed button
      const swatches = node.dataset.look === "swatches";
      return { keys, draw: bindButtons(node, swatches ? "btn swatch" : "btn seg", list,
        (value) => set({ [key]: value }), (value, prefs) => value === prefs[key], swatches ? swatch : null) };
    }
  }
}

// "alpha=50,100,150 width=100,100,150": a column, and its numbers.
function columns(text) {
  return Object.fromEntries(words(text).map((word) => {
    const [column, numbers] = word.split("=");
    return [column, numbers.split(",").map(Number)];
  }));
}

// Some rows of a table (the map's layers): each .layer[data-row] gets a
// SHOW switch and a row of weights. A weight is the row's own default
// cells, each scaled by its column's percent for that weight (data-scales)
// and held to the column's most (data-most), so NORMAL is the default and a
// row set to none of them lights none. Only the cells changed are sent:
// {t: "prefs", key: {ROW: {col: value}}}, which the server merges cell by cell.
function bindLayers(node, set, current, defaults) {
  const key = node.dataset.pref;
  const weights = options(node.dataset.values).map(([label], i) => [label, i]);
  const scales = columns(node.dataset.scales);
  const most = columns(node.dataset.most);
  const layers = [...node.querySelectorAll("[data-row]")].map((line) => {
    const { row } = line.dataset;
    const name = line.querySelector(".name");
    const said = name.textContent.toLowerCase();
    const normal = defaults[key][row];
    const cells = (weight) => Object.fromEntries(Object.entries(scales)
      .filter(([column]) => column in normal)
      .map(([column, percents]) => [column,
        Math.min(most[column]?.[0] ?? Infinity, Math.round((normal[column] * percents[weight]) / 100))]));
    const now = () => current()[key]?.[row] || {};
    const show = button("btn layer-show", "", () => set({ [key]: { [row]: { show: !now().show } } }));
    show.append(document.createElement("i"));
    show.setAttribute("aria-label", `Show ${said}`);
    const group = document.createElement("div");
    group.className = "segments small";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", `${said} weight`);
    const drawWeights = bindButtons(group, "btn seg", weights,
      (weight) => set({ [key]: { [row]: cells(weight) } }),
      (weight, cellsNow) => Object.entries(cells(weight)).every(([column, value]) => cellsNow[column] === value));
    line.prepend(show);
    line.append(group);
    return { row, line, name, show, group, drawWeights };
  });
  const changedRow = (prefs, row) => !same(prefs[key]?.[row], defaults[key][row]);
  return {
    keys: [key],
    draw(prefs) {
      for (const { row, line, name, show, group, drawWeights } of layers) {
        const cellsNow = prefs[key]?.[row] || {};
        const on = Boolean(cellsNow.show);
        show.setAttribute("aria-pressed", String(on));
        line.classList.toggle("off", !on);
        drawWeights(cellsNow);
        for (const made of group.children) made.disabled = !on;
        dot(name, changedRow(prefs, row));
      }
    },
    changed: (prefs) => layers.some(({ row }) => changedRow(prefs, row)),
    reset: () => ({ [key]: Object.fromEntries(layers.map(({ row }) => [row, defaults[key][row]])) }),
  };
}

// The mark beside a name whose setting is not the default.
function dot(name, on) {
  const have = name.querySelector(".dot");
  if (on === Boolean(have)) return;
  if (have) { have.remove(); return; }
  const made = document.createElement("i");
  made.className = "dot";
  made.title = "Changed from the default";
  name.append(made);
}

// Changes laid over changes: a table's rows together, anything else whole.
function gather(list) {
  const out = {};
  for (const changes of list) {
    for (const [key, value] of Object.entries(changes)) {
      const table = value && typeof value === "object" && !Array.isArray(value);
      out[key] = table ? { ...out[key], ...value } : value;
    }
  }
  return out;
}

// The tabs: buttons over panels, one shown. A click or the arrow keys (and
// Home and End) pick one; only the picked tab is in the Tab order. The
// panel reopens on the last one picked, for as long as the page is open.
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
  return { current: () => tabs.find((tab) => tab.tabIndex === 0) };
}

// `opener` is the header's gear, which opens the panel and closes it, and
// says which with aria-expanded; <html data-config> is ON while it is open,
// for the stylesheet to move the page over. `resetAll` is the foot's button.
export function mountConfigSheet({ sheet, opener, resetAll }, store, send) {
  const { defaults } = store;
  const tabs = mountTabs(sheet);
  const set = (changes) => send({ t: "prefs", ...changes });
  const current = () => store.state.prefs;
  const plain = (keys) => ({
    changed: (prefs) => keys.some((key) => !same(prefs[key], defaults[key])),
    reset: () => Object.fromEntries(keys.map((key) => [key, defaults[key]])),
  });

  const controls = [...sheet.querySelectorAll("[data-pref]")].map((node) => {
    const bound = node.dataset.kind === "layers"
      ? bindLayers(node, set, current, defaults)
      : bindControl(node, store, set, current);
    const row = node.closest(".field-row");
    return {
      node, row, name: row?.querySelector(".name"), group: node.closest(".group"),
      // data-only-when="display=CRT": the control works only with that so;
      // data-not-when="tail_secs=0": it does not work with that so.
      works: (prefs) => (!node.dataset.onlyWhen || holds(node.dataset.onlyWhen, prefs))
        && !(node.dataset.notWhen && holds(node.dataset.notWhen, prefs)),
      ...plain(bound.keys), ...bound,
    };
  });

  // Each group of rows has a RESET in its head, shown while any of its
  // settings is not the default.
  const groups = [...sheet.querySelectorAll(".group")].map((group) => {
    const mine = controls.filter((control) => control.group === group);
    const reset = button("reset", "RESET", () => set(gather(mine.map((control) => control.reset()))));
    reset.setAttribute("aria-label", `Reset ${group.querySelector("h3").textContent.toLowerCase()}`);
    reset.hidden = true;
    group.querySelector(".group-head").append(reset);
    return { mine, reset };
  });

  // Every setting, but those the button keeps, whether or not it has a
  // control here: one that has none can be put back no other way.
  resetAll.addEventListener("click", () => {
    const keep = words(resetAll.dataset.keep);
    set(Object.fromEntries(Object.entries(defaults).filter(([key]) => !keep.includes(key))));
  });

  function render() {
    const prefs = current();
    for (const { node, row, name, draw, works, changed } of controls) {
      draw(prefs);
      if (name) dot(name, changed(prefs));
      if (!row) continue;
      const off = !works(prefs);
      for (const part of node.matches("select") ? [node] : node.querySelectorAll("button")) part.disabled = off;
      row.classList.toggle("off", off);
    }
    for (const { mine, reset } of groups) reset.hidden = !mine.some((control) => control.changed(prefs));
  }

  function shown(open) {
    document.documentElement.dataset.config = open ? "ON" : "OFF";
    opener.setAttribute("aria-expanded", String(open));
  }
  function open() {
    render();
    if (sheet.open) return;
    sheet.show(); // not showModal: the cockpit stays in use beside the panel
    shown(true);
    tabs.current().focus();
  }
  const close = () => sheet.close();
  // However it closes (the X, Escape, the gear), the gear has the focus back.
  sheet.addEventListener("close", () => { shown(false); opener.focus(); });
  // A dialog that is not modal does not close on Escape of its own accord.
  sheet.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.isComposing) return;
    event.preventDefault();
    close();
  });

  store.subscribe((kind) => { if (kind === "all" || kind === "prefs") render(); });
  render();
  return { open, close, toggle() { if (sheet.open) close(); else open(); } };
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
