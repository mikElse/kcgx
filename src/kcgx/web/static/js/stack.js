// The frequency stack (spec, The feed stack in this language). An audible
// feed is an expanded row: name, an oscilloscope trace of its level, M and S.
// A muted feed is one compact line, and the whole line is a button that
// unmutes it. Rows are moved, never rebuilt, when the order changes, so a
// trace keeps its history across a reorder.

import { HISTORY } from "./store.js";
import { colours, glowBlur } from "./theme.js";

const GLYPHS = { live: "●", reconnecting: "◐", starting: "◐", offline: "○", parked: "‖" };
const STATES = { live: "LIVE", reconnecting: "RECONNECTING", starting: "STARTING", offline: "OFFLINE", parked: "PARKED" };
const INPUT_EVERY_MS = 1000;

const two = (fraction) => String(Math.round((fraction || 0) * 100)).padStart(2, "0");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function mountStack({ stack, counts }, store, send) {
  const rows = new Map(); // ident -> { node, shape, parts }
  let levelsDirty = false;

  function stateGlyph(feed) {
    const span = el("span", `feed-state state-${feed.state}`, GLYPHS[feed.state] || "●");
    span.title = STATES[feed.state] || feed.state.toUpperCase();
    span.setAttribute("aria-label", span.title);
    return span;
  }

  function buildExpanded(feed) {
    const node = el("div", "feed expanded");
    const head = el("div", "feed-head");
    const name = el("span", "feed-name", feed.name);
    const glyph = stateGlyph(feed);
    head.append(name, glyph);
    const trace = el("canvas", "trace");
    trace.setAttribute("aria-hidden", "true");
    const controls = el("div", "feed-controls");
    const mute = el("button", "btn", "M");
    mute.type = "button";
    mute.addEventListener("click", () => send({ t: "mute", ident: feed.ident }));
    const solo = el("button", "btn", "S");
    solo.type = "button";
    solo.addEventListener("click", () => send({ t: "solo", ident: feed.ident }));
    const label = el("span", "chatter-label", "CHATTER");
    const chatter = el("span", "chatter-big", two(feed.chatter));
    controls.append(mute, solo, el("span", "spacer"), label, chatter);
    node.append(head, trace, controls);
    return { node, parts: { name, glyph, trace, mute, solo, chatter } };
  }

  function buildCompact(feed) {
    const node = el("button", "feed compact");
    node.type = "button";
    node.addEventListener("click", () => send({ t: "mute", ident: feed.ident }));
    const name = el("span", "feed-name", feed.name);
    const note = el("span", "note", "♪");
    note.setAttribute("aria-hidden", "true");
    const chatter = el("span", "chatter-small", two(feed.chatter));
    const glyph = stateGlyph(feed);
    node.append(name, note, chatter, glyph);
    return { node, parts: { name, glyph, chatter } };
  }

  function update(row, feed) {
    const { parts } = row;
    parts.name.textContent = feed.name;
    parts.glyph.textContent = GLYPHS[feed.state] || "●";
    parts.glyph.className = `feed-state state-${feed.state}`;
    parts.glyph.title = STATES[feed.state] || feed.state.toUpperCase();
    parts.glyph.setAttribute("aria-label", parts.glyph.title);
    parts.chatter.textContent = two(feed.chatter);
    if (row.shape === "expanded") {
      parts.mute.setAttribute("aria-pressed", String(feed.muted));
      parts.mute.setAttribute("aria-label", `Mute ${feed.name}`);
      parts.solo.setAttribute("aria-pressed", String(feed.soloed));
      parts.solo.setAttribute("aria-label", `Solo ${feed.name}`);
    } else {
      row.node.classList.toggle("parked", feed.state === "parked");
      row.node.setAttribute(
        "aria-label",
        `Unmute ${feed.name}, chatter ${two(feed.chatter)} percent, ${parts.glyph.title.toLowerCase()}`,
      );
    }
  }

  function render() {
    const { state } = store;
    const wanted = new Set(state.order);
    for (const [ident, row] of rows) {
      if (!wanted.has(ident)) { row.node.remove(); rows.delete(ident); }
    }
    let previous = null;
    for (const ident of state.order) {
      const feed = state.feeds.get(ident);
      if (!feed) continue;
      const shape = feed.muted ? "compact" : "expanded";
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
    renderCounts();
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

  function renderCounts() {
    const { state } = store;
    const feeds = [...state.feeds.values()];
    const live = feeds.filter((f) => f.state === "live").length;
    const parked = feeds.filter((f) => f.state === "parked").length;
    counts.replaceChildren(
      el("span", "", `${feeds.length} FEEDS`),
      el("span", "", `${live} LIVE  ${parked} PARKED`),
      el("span", "", `VOL ${Math.round(state.volume * 100)}%`),
    );
  }

  // -- the traces ---------------------------------------------------------------

  function drawTrace(canvas, ident) {
    const ratio = window.devicePixelRatio || 1;
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
    ctx.shadowBlur = glowBlur() * ratio;
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

  function frame() {
    if (levelsDirty) {
      levelsDirty = false;
      for (const [ident, row] of rows) {
        if (row.shape === "expanded") drawTrace(row.parts.trace, ident);
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

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
