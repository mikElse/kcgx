// The frequency stack (spec, The feed stack in this language). One feed is
// heard at a time, picked like a radio button (phase G decision 3). The
// audible feed is the expanded row: its title, chatter and state, and an
// oscilloscope trace of its level. Every other feed is one compact line, and
// the whole line is a button that selects it; the expanded row is no button,
// as picking what is playing does nothing. Rows are moved, never rebuilt,
// when the order changes, so a trace keeps its history across a reorder.
//
// The pane's header, the master mute and the volume, is mountVolume below.

import { HISTORY } from "./store.js";
import { colours, glowBlur, renderScale } from "./theme.js";
import { onFrame } from "./frames.js";

const GLYPHS = { live: "●", reconnecting: "◐", starting: "◐", offline: "○", parked: "‖" };
const STATES = { live: "LIVE", reconnecting: "RECONNECTING", starting: "STARTING", offline: "OFFLINE", parked: "PARKED" };
const INPUT_EVERY_MS = 1000;

// Chatter is a share of the time, shown as a whole percentage.
const whole = (fraction) => Math.round((fraction || 0) * 100);
const percent = (fraction) => `${whole(fraction)}%`;

// What a row is called: the title (the name without the airport, by the
// short_names setting), from the server.
const titleOf = (feed) => feed.title || feed.name;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function mountStack({ stack }, store, send) {
  const rows = new Map(); // ident -> { node, shape, parts }
  let levelsDirty = false;

  function stateGlyph(feed) {
    const span = el("span", `feed-state state-${feed.state}`, GLYPHS[feed.state] || "●");
    span.title = STATES[feed.state] || feed.state.toUpperCase();
    span.setAttribute("aria-label", span.title);
    return span;
  }

  // Name, chatter and state, left to right, as in a compact row.
  function buildExpanded(feed) {
    const node = el("div", "feed expanded");
    node.setAttribute("role", "group");
    const head = el("div", "feed-head");
    const name = el("span", "feed-name", titleOf(feed));
    const chatter = el("span", "chatter-big", percent(feed.chatter));
    const glyph = stateGlyph(feed);
    head.append(name, chatter, glyph);
    const trace = el("canvas", "trace");
    trace.setAttribute("aria-hidden", "true");
    node.append(head, trace);
    return { node, parts: { name, glyph, trace, chatter } };
  }

  function buildCompact(feed) {
    const node = el("button", "feed compact");
    node.type = "button";
    node.addEventListener("click", () => send({ t: "select", ident: feed.ident }));
    const name = el("span", "feed-name", titleOf(feed));
    const note = el("span", "note", "♪");
    note.setAttribute("aria-hidden", "true");
    const chatter = el("span", "chatter-small", percent(feed.chatter));
    const glyph = stateGlyph(feed);
    node.append(name, note, chatter, glyph);
    return { node, parts: { name, glyph, chatter } };
  }

  function update(row, feed) {
    const { parts } = row;
    const title = titleOf(feed);
    parts.name.textContent = title;
    parts.glyph.textContent = GLYPHS[feed.state] || "●";
    parts.glyph.className = `feed-state state-${feed.state}`;
    parts.glyph.title = STATES[feed.state] || feed.state.toUpperCase();
    parts.glyph.setAttribute("aria-label", parts.glyph.title);
    parts.chatter.textContent = percent(feed.chatter);
    const said = `chatter ${whole(feed.chatter)} percent, ${parts.glyph.title.toLowerCase()}`;
    if (row.shape === "expanded") {
      row.node.setAttribute("aria-label", `Playing ${title}, ${said}`);
    } else {
      row.node.classList.toggle("parked", feed.state === "parked");
      row.node.setAttribute("aria-label", `Listen to ${title}, ${said}`);
    }
  }

  // The expanded row is the feed that is not muted. The server keeps that
  // to one; should /debug unmute more, the first in the stack is expanded,
  // and a click on another of them selects it.
  function playing() {
    const { state } = store;
    return state.order.find((ident) => state.feeds.get(ident)?.muted === false);
  }

  function render() {
    const { state } = store;
    const wanted = new Set(state.order);
    const heard = playing();
    for (const [ident, row] of rows) {
      if (!wanted.has(ident)) { row.node.remove(); rows.delete(ident); }
    }
    let previous = null;
    for (const ident of state.order) {
      const feed = state.feeds.get(ident);
      if (!feed) continue;
      const shape = ident === heard ? "expanded" : "compact";
      let row = rows.get(ident);
      if (!row || row.shape !== shape) {
        const built = shape === "expanded" ? buildExpanded(feed) : buildCompact(feed);
        const fresh = { ...built, shape };
        if (row) row.node.replaceWith(fresh.node);
        row = fresh;
        rows.set(ident, row);
        row.node.dataset.ident = ident;
      }
      update(row, feed);
      // Move only what is out of place: a moved node keeps its canvas.
      const expectedNext = previous ? previous.nextSibling : stack.firstChild;
      if (row.node !== expectedNext) stack.insertBefore(row.node, expectedNext);
      previous = row.node;
    }
    renderEmpty();
    levelsDirty = true;
  }

  function renderEmpty() {
    const { state } = store;
    let message = "";
    if (!state.connected && !state.airport) message = "CONNECTING";
    else if (state.loading) message = `LOADING FEEDS FOR ${state.airport ? state.airport.icao : ""}`;
    else if (state.order.length === 0) message = `NO FEEDS AT ${state.airport ? state.airport.icao : "THIS AIRPORT"}`;
    let empty = stack.querySelector(".stack-empty");
    if (message) {
      if (!empty) { empty = el("p", "stack-empty"); stack.append(empty); }
      empty.textContent = message;
    } else if (empty) {
      empty.remove();
    }
  }

  // -- the traces ---------------------------------------------------------------

  // Backing store by the render scale (phase G decision 6): at OFF, half
  // the pixels, scaled up hard; the glow is the traffic layer's.
  function drawTrace(canvas, ident) {
    const scale = renderScale();
    const ratio = (window.devicePixelRatio || 1) * scale;
    canvas.style.imageRendering = scale < 1 ? "pixelated" : "";
    const width = Math.max(1, Math.round(canvas.clientWidth * ratio));
    const height = Math.max(1, Math.round(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext("2d");
    const c = colours();
    ctx.clearRect(0, 0, width, height);
    const mid = height / 2;
    ctx.save();
    ctx.strokeStyle = c.dim;
    ctx.lineWidth = Math.max(1, 0.6 * ratio);
    ctx.setLineDash([1 * ratio, 4 * ratio]);
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(width, mid); ctx.stroke();
    ctx.restore();

    const h = store.historyFor(ident);
    ctx.save();
    ctx.strokeStyle = c.cyan;
    ctx.lineWidth = 1.2 * ratio;
    ctx.lineJoin = "round";
    ctx.shadowColor = c.cyan;
    ctx.shadowBlur = glowBlur("traffic") * ratio;
    ctx.beginPath();
    for (let i = 0; i < HISTORY; i += 1) {
      const slot = (h.next + i) % HISTORY;
      const db = h.samples[slot];
      const amp = Math.min(1, Math.max(0, (db + 70) / 58));
      const sign = slot % 2 ? 1 : -1;
      const x = (i / (HISTORY - 1)) * width;
      const y = mid + sign * amp * mid * 0.92;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  onFrame(() => {
    if (!levelsDirty) return;
    levelsDirty = false;
    for (const [ident, row] of rows) {
      if (row.shape === "expanded") drawTrace(row.parts.trace, ident);
    }
  });

  // The viewer's hand on the stack holds the resort (spec, Feature parity).
  let lastInput = 0;
  stack.addEventListener("pointermove", () => {
    const now = performance.now();
    if (now - lastInput > INPUT_EVERY_MS) { lastInput = now; send({ t: "input" }); }
  });

  store.subscribe((kind) => {
    if (kind === "levels") levelsDirty = true;
    else if (kind === "prefs") levelsDirty = true;
    else if (kind !== "message") render();
  });
  window.addEventListener("resize", () => { levelsDirty = true; });
  render();
}

// -- the pane's header: the master mute and volume ----------------------------------
//
// Neither is a pref: they are the server's audio state, and live here, not in
// the config sheet (phase G decision 3). The mute silences everything and
// keeps the volume and the picked feed as they were. Like a slider in the
// sheet, a frame from the server does not move the volume while it has the
// focus.

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

export function mountVolume({ mute, volume, volumeValue }, store, send) {
  mute.addEventListener("click", () => send({ t: "master_mute", on: !store.state.muted }));
  const sendVolume = debounce((value) => send({ t: "volume", value }), 60);
  volume.addEventListener("input", () => {
    volumeValue.textContent = `${volume.value}%`;
    sendVolume(Number(volume.value) / 100);
  });
  function render() {
    const { muted } = store.state;
    mute.setAttribute("aria-pressed", String(muted));
    mute.setAttribute("aria-label", muted ? "Unmute all feeds" : "Mute all feeds");
    mute.title = muted ? "UNMUTE" : "MUTE";
    if (document.activeElement === volume) return;
    volume.value = String(Math.round(store.state.volume * 100));
    volumeValue.textContent = `${volume.value}%`;
  }
  store.subscribe((kind) => { if (kind === "all" || kind === "volume") render(); });
  render();
}
