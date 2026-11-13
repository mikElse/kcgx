// The cockpit page: one store, one connection, and the views that draw it.
// Every action is a click (spec, Every action is a click).

import { createStore } from "./store.js";
import { connect } from "./connection.js";
import { bindTheme, fontFamilies, forget, textGlow } from "./theme.js";
import { setFont } from "./radar/draw.js";
import { bindFrames } from "./frames.js";
import { mountStack, mountVolume } from "./stack.js";
import { mountStatus } from "./status.js";
import { mountLamps } from "./lamps.js";
import { mountLog } from "./log.js";
import { mountRadar } from "./radar/index.js";
import { mountTracks } from "./tracks.js";
import { mountAirportSheet, mountConfigSheet, mountShutdownSheet } from "./sheets.js";

const $ = (id) => document.getElementById(id);
const store = createStore();
bindFrames(store); // the frame rate cap, prefs.fps_max
bindTheme(store); // renderScale(), glowBlur(layer)
const link = connect(store);
const send = (message) => link.send(message);

function applyPrefs() {
  const { prefs } = store.state;
  const root = document.documentElement;
  root.dataset.palette = prefs.palette;
  // The page's glow is the text layer's (glow_text); the canvases read
  // their own layers from theme.js.
  const glow = textGlow();
  root.style.setProperty("--glow", glow.glow);
  root.style.setProperty("--frame-glow", glow.frame);
  root.style.setProperty("--lamp-glow", glow.lamp);
  // The page's size and face: zoom scales it all, sheets too; the font size
  // is the text's, not the titles' or the big figures'; the display font is
  // the radar's as well, whose static layer the prefs redraw.
  root.style.setProperty("--ui-zoom", String(prefs.ui_zoom));
  root.style.setProperty("--font-px", `${prefs.font_px}px`);
  const fonts = fontFamilies(prefs.font);
  root.style.setProperty("--font-text", fonts.text);
  root.style.setProperty("--font-display", fonts.display);
  setFont(fonts.display);
  root.dataset.display = prefs.display;
  // The scanlines: the pitch is the setting, the dark line a third of it.
  root.style.setProperty("--scan-alpha", String(prefs.scan_opacity / 100));
  root.style.setProperty("--scan-size", `${prefs.scan_size}px`);
  root.style.setProperty("--scan-line", `${Math.max(1, Math.round(prefs.scan_size / 3))}px`);
  $("radar-range").textContent = `RNG ${prefs.range_nm} NM`;
  // The label boxes. The radar paints its own; the readouts over it are
  // boxed by the stylesheet, from the same four settings.
  root.dataset.boxHud = prefs.box_items.includes("HUD") ? "ON" : "OFF";
  root.style.setProperty("--box-fill", `${prefs.box_fill}%`);
  root.style.setProperty("--box-pad", `${prefs.box_pad}px`);
  root.style.setProperty("--box-border", `${prefs.box_border}%`);
  root.style.setProperty("--box-width", `${prefs.box_width}px`);
  root.dataset.lamps = prefs.lamps ? "ON" : "OFF";
  const opened = prefs.teletype && root.dataset.teletype !== "ON";
  root.dataset.teletype = prefs.teletype ? "ON" : "OFF";
  // The teletype kept collecting while it was hidden, but a hidden pane
  // cannot scroll: open it on its newest line. Its errors are in view
  // again, so the banner gives them up.
  if (opened) $("log").scrollTop = $("log").scrollHeight;
  if (prefs.teletype) raised.clear();
  forget();
}

// Hiding the teletype must not hide errors: while it is hidden, a line
// from the page itself (a failed request, a message the server refused)
// also shows in the banner, for RAISED_MS. Server notes do not; they are
// history, and turning the teletype on shows them.
const RAISED_MS = 8000;
const raised = {
  text: "",
  timer: 0,
  show(text) {
    if (store.state.prefs.teletype) return;
    clearTimeout(this.timer);
    this.text = text.toUpperCase();
    this.timer = setTimeout(() => this.clear(), RAISED_MS);
    banner();
  },
  clear() {
    if (!this.text) return;
    clearTimeout(this.timer);
    this.text = "";
    banner();
  },
};

// The teletype is mounted whether or not it shows, so it is whole when it does.
const teletype = mountLog($("log"), store);
const log = { say(text) { teletype.say(text); raised.show(text); } };
mountStack({ stack: $("stack") }, store, send);
mountVolume({ mute: $("master-mute"), volume: $("volume"), volumeValue: $("volume-value") }, store, send);
mountStatus({
  icao: $("icao"), name: $("airport-name"), where: $("airport-where"), zulu: $("zulu"), local: $("local"),
}, store);
mountLamps($("lamps"), store);
const radar = mountRadar($("radar"), store, {
  hud: { poll: $("radar-poll"), tracks: $("radar-tracks"), position: $("radar-position") },
});
mountTracks({ head: $("tracks-head"), body: $("tracks-body"), empty: $("tracks-empty") }, store);

const airportSheet = mountAirportSheet(
  { sheet: $("airport-sheet"), query: $("airport-query"), results: $("airport-results") }, store, log,
);
const configSheet = mountConfigSheet({ sheet: $("config-sheet") }, store, send);
const shutdownSheet = mountShutdownSheet({ sheet: $("shutdown-sheet") }, store, () => {
  store.setShutdown();
  link.stop();
  $("ended").hidden = false;
  // In KCGX.app the window closes with the cockpit (macos/KCGXWindow.swift).
  // A browser has no such handler, and this does nothing.
  window.webkit?.messageHandlers?.kcgx?.postMessage("ended");
}, log);

$("open-airport").addEventListener("click", () => airportSheet.open());
$("open-config").addEventListener("click", () => configSheet.open());
$("open-shutdown").addEventListener("click", () => shutdownSheet.open());

// `kcgx go` with no airport, or one that names several, opens the page at
// #airport or #airport=<query>: the search opens with the query typed.
// Anybody can write a link, and KCGX.app passes on the fragment of a kcgx://
// link as it came (macos/KCGXWindow.swift), so the query may be badly
// escaped: it is then taken as written. Nothing here may throw, because the
// rest of the page is set up below.
function fromLink() {
  const match = /^#airport(?:=(.*))?$/.exec(location.hash);
  if (!match) return;
  history.replaceState(null, "", location.pathname + location.search);
  let query = match[1] || "";
  try {
    query = decodeURIComponent(query);
  } catch {
    // "%E9", "100%": no escape of anything, so the text itself.
  }
  airportSheet.open(query);
}
window.addEventListener("hashchange", fromLink);
fromLink();
window.kcgx = { radar, store, send }; // for the browser tests

function banner() {
  const { state } = store;
  const node = $("banner");
  let text = "";
  let kind = "";
  if (state.shutdown) text = "";
  else if (raised.text) { text = raised.text; kind = "bad"; }
  else if (!state.connected) { text = "CONNECTION LOST. RECONNECTING TO THE KCGX SERVER"; kind = "warn"; }
  else if (!state.audioOk) { text = "NO AUDIO OUTPUT ON THE SERVER. THE FEEDS STILL RUN; CHECK THE SOUND DEVICE"; kind = "bad"; }
  node.hidden = !text;
  node.textContent = text;
  node.className = `banner ${kind}`.trim();
}

// A face that arrives after the static layer was drawn in the one before it.
document.fonts.addEventListener("loadingdone", () => radar.redraw());
store.subscribe((kind, detail) => {
  if (kind === "all" || kind === "prefs") { applyPrefs(); radar.redraw(); }
  if (kind === "all" || kind === "connection") banner();
  if (kind === "message" && detail.page) raised.show(detail.text);
});
banner();
$("where-served").textContent = `LOCAL COCKPIT  ${location.host}`;
