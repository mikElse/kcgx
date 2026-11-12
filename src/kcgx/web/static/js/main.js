// The cockpit page: one store, one connection, and the views that draw it.
// Every action is a click (spec, Every action is a click).

import { createStore } from "./store.js";
import { connect } from "./connection.js";
import { forget } from "./theme.js";
import { mountStack } from "./stack.js";
import { mountStatus } from "./status.js";
import { mountLamps } from "./lamps.js";
import { mountLog } from "./log.js";
import { mountRadar } from "./radar.js";
import { mountTracks } from "./tracks.js";
import {
  CHOICES, mountAirportSheet, mountConfigSheet, mountFeedsSheet, mountShutdownSheet,
} from "./sheets.js";

const $ = (id) => document.getElementById(id);
const store = createStore();
const link = connect(store);
const send = (message) => link.send(message);

function applyPrefs() {
  const { prefs } = store.state;
  const root = document.documentElement;
  root.dataset.palette = prefs.palette;
  root.dataset.glow = prefs.glow;
  root.dataset.display = prefs.display;
  root.dataset.lamps = prefs.lamps ? "ON" : "OFF";
  const opened = prefs.teletype && root.dataset.teletype !== "ON";
  root.dataset.teletype = prefs.teletype ? "ON" : "OFF";
  // The teletype kept collecting while it was hidden, but a hidden pane
  // cannot scroll: open it on its newest line. Its errors are in view
  // again, so the banner gives them up.
  if (opened) $("log").scrollTop = $("log").scrollHeight;
  if (prefs.teletype) raised.clear();
  $("palette-name").textContent = prefs.palette;
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
const stack = mountStack({ stack: $("stack"), counts: $("freq-counts") }, store, send);
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
const feedsSheet = mountFeedsSheet(
  { sheet: $("feeds-sheet"), query: $("feeds-query"), status: $("feeds-status"), results: $("feeds-results") },
  store, send, (ident) => setTimeout(() => stack.show(ident), 300),
);
const configSheet = mountConfigSheet(
  { sheet: $("config-sheet"), volume: $("volume"), volumeValue: $("volume-value"), maxStreams: $("max-streams") },
  store, send,
);
const shutdownSheet = mountShutdownSheet({ sheet: $("shutdown-sheet") }, store, () => {
  store.setShutdown();
  link.stop();
  $("ended").hidden = false;
}, log);

$("open-airport").addEventListener("click", () => airportSheet.open());
$("open-feeds").addEventListener("click", () => feedsSheet.open());
$("open-config").addEventListener("click", () => configSheet.open());
$("open-shutdown").addEventListener("click", () => shutdownSheet.open());
$("next-palette").addEventListener("click", () => {
  const all = CHOICES.palette;
  const next = all[(all.indexOf(store.state.prefs.palette) + 1) % all.length];
  send({ t: "prefs", palette: next });
});
$("recentre").addEventListener("click", () => radar.recentre());

// `kcgx go` with no airport, or one that names several, opens the page at
// #airport or #airport=<query>: the search opens with the query typed.
function fromLink() {
  const match = /^#airport(?:=(.*))?$/.exec(location.hash);
  if (!match) return;
  history.replaceState(null, "", location.pathname + location.search);
  airportSheet.open(match[1] ? decodeURIComponent(match[1]) : "");
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

store.subscribe((kind, detail) => {
  if (kind === "all" || kind === "prefs") { applyPrefs(); radar.redraw(); }
  if (kind === "all" || kind === "connection") banner();
  if (kind === "message" && detail.page) raised.show(detail.text);
});
banner();
$("where-served").textContent = `LOCAL COCKPIT  ${location.host}`;
