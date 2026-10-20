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
  $("palette-name").textContent = prefs.palette;
  forget();
}

const log = mountLog($("log"), store);
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
window.kcgx = { radar, store }; // for the browser tests

function banner() {
  const { state } = store;
  const node = $("banner");
  let text = "";
  let kind = "";
  if (state.shutdown) text = "";
  else if (!state.connected) { text = "CONNECTION LOST. RECONNECTING TO THE KCGX SERVER"; kind = "warn"; }
  else if (!state.audioOk) { text = "NO AUDIO OUTPUT ON THE SERVER. THE FEEDS STILL RUN; CHECK THE SOUND DEVICE"; kind = "bad"; }
  node.hidden = !text;
  node.textContent = text;
  node.className = `banner ${kind}`.trim();
}

store.subscribe((kind) => {
  if (kind === "all" || kind === "prefs") { applyPrefs(); radar.redraw(); }
  if (kind === "all" || kind === "connection") banner();
});
banner();
$("where-served").textContent = `LOCAL COCKPIT  ${location.host}`;
