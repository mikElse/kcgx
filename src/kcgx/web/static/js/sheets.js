// The three sheets: change airport, config and shut down. Each is a
// <dialog>, so focus, Escape and the backdrop come from the browser.

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

function bindSelect(node, set) {
  node.addEventListener("change", () => set(node.value));
  return (value) => { node.value = value; };
}

// A slider shows what it is dragged to at once and sends it a moment
// later. While it is in hand (focused, or with a send still to go) a frame
// from the server does not move it, as the volume slider is not moved.
function bindSlider(node, set, redraw) {
  const readout = node.parentElement.querySelector("[data-unit]");
  const show = (value) => {
    if (!readout) return;
    const unit = readout.dataset.unit;
    readout.textContent = unit === "%" ? `${value}%` : `${value} ${unit}`;
  };
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

function bind(node, store, send, redraw) {
  const key = node.dataset.pref;
  const set = (value) => send({ t: "prefs", [key]: value });
  if (node.tagName === "SELECT") return bindSelect(node, set);
  if (node.tagName === "INPUT") return bindSlider(node, set, redraw);
  const names = (node.dataset.values || "").split(" ").filter(Boolean).map((name) => [name, name]);
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
        const answered = kind === "prefs" && asked && String(store.state.prefs[key]) === String(asked);
        if (kind === "all" || answered) asked = null;
      });
      return bindSegments(node, names, (name) => {
        const now = asked || store.state.prefs[key] || [];
        asked = names.map(([n]) => n).filter((n) => (n === name) !== now.includes(n));
        set(asked);
      }, (value, setting) => (setting || []).includes(value));
    }
    default: // a choice: one pressed button
      return bindSegments(node, names, set, (value, setting) => value === setting);
  }
}

export function mountConfigSheet({ sheet, volume, volumeValue }, store, send) {
  const controls = [...sheet.querySelectorAll("[data-pref]")].map((node) => {
    // data-only-when="display=CRT": the control works only with that setting so.
    const [needs, needed] = (node.dataset.onlyWhen || "").split("=");
    return { node, key: node.dataset.pref, needs, needed, draw: bind(node, store, send, () => render()) };
  });

  const sendVolume = debounce((value) => send({ t: "volume", value }), 60);
  volume.addEventListener("input", () => {
    volumeValue.textContent = `${volume.value}%`;
    sendVolume(Number(volume.value) / 100);
  });

  function render() {
    const { state } = store;
    if (document.activeElement !== volume) {
      volume.value = String(Math.round(state.volume * 100));
      volumeValue.textContent = `${volume.value}%`;
    }
    for (const { node, key, needs, needed, draw } of controls) {
      draw(state.prefs[key]);
      if (!needs) continue;
      const off = state.prefs[needs] !== needed;
      for (const part of node.matches("input, select") ? [node] : node.children) part.disabled = off;
      node.closest(".field-row").classList.toggle("off", off);
    }
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "volume" || kind === "prefs") render(); });
  render();
  return { open() { render(); if (!sheet.open) sheet.showModal(); } };
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
