// The four sheets: change airport, feeds, config and shut down. Each is a
// <dialog>, so focus, Escape and the backdrop come from the browser.

const CHOICES = {
  palette: ["WOPR", "AMBER", "MATRIX", "MONO"],
  glow: ["OFF", "LOW", "FULL"],
  display: ["OFF", "VECTOR", "CRT"],
};

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

export function mountFeedsSheet({ sheet, query, status, results }, store, send, onOpened) {
  let feeds = [];

  function draw() {
    const filter = query.value.trim().toLowerCase();
    const shown = feeds.filter((f) => !filter || f.label.toLowerCase().includes(filter) || f.ident.includes(filter));
    status.textContent = `${feeds.length} FEEDS AT ${store.state.airport ? store.state.airport.icao : ""}, ${feeds.filter((f) => f.open).length} OPEN`;
    results.replaceChildren(...shown.map((feed) => {
      const node = button("choice", "", () => {
        if (!feed.open) send({ t: "open_feed", ident: feed.ident });
        sheet.close();
        onOpened(feed.ident);
      });
      const name = document.createElement("span");
      name.className = "what";
      name.textContent = feed.label.toUpperCase();
      const tag = document.createElement("span");
      tag.className = feed.open ? "tag on" : "tag";
      tag.textContent = feed.open ? "OPEN" : "ADD";
      node.append(name, tag);
      return node;
    }));
  }

  query.addEventListener("input", draw);
  return {
    async open() {
      query.value = "";
      feeds = [];
      results.replaceChildren();
      status.textContent = "LOADING THE FEED LIST";
      sheet.showModal();
      query.focus();
      try {
        feeds = await json("/api/feeds/available");
      } catch {
        status.textContent = "COULD NOT LOAD THE FEED LIST";
        return;
      }
      draw();
    },
  };
}

export function mountConfigSheet({ sheet, volume, volumeValue, maxStreams }, store, send) {
  const groups = [...sheet.querySelectorAll(".segments")];
  for (const group of groups) {
    const pref = group.dataset.pref;
    group.replaceChildren(...CHOICES[pref].map((value) => {
      const node = button("btn seg", value, () => send({ t: "prefs", [pref]: value }));
      node.dataset.value = value;
      return node;
    }));
  }

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
    maxStreams.textContent = String(state.maxStreams);
    for (const group of groups) {
      const current = state.prefs[group.dataset.pref];
      for (const node of group.children) node.setAttribute("aria-pressed", String(node.dataset.value === current));
    }
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "volume" || kind === "prefs") render(); });
  render();
  return { open() { render(); sheet.showModal(); } };
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

export { CHOICES };
