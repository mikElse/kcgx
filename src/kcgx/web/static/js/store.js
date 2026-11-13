// The page's copy of the server's state, built only from protocol frames
// (spec, Transport). Views never change it; they send messages and wait for
// the server's answer, so every tab shows exactly what the server applied.

export const HISTORY = 160; // level samples kept per feed: 6.4 s at 25 Hz
export const SILENT = -96;
export const TRAIL = 12; // positions kept per aircraft: three minutes of polls

export function createStore() {
  const state = {
    connected: false,
    shutdown: false,
    airport: null,
    loading: true,
    feeds: new Map(), // ident -> feed view
    order: [], // idents, stack order
    volume: 1,
    audioOk: true,
    // kcgx.prefs.DEFAULTS, until the first snapshot brings the server's.
    prefs: {
      // General
      boot_anim: true,
      ui_zoom: 100,
      font: "CLASSIC",
      font_px: 13,
      clock_24h: true,
      clock_seconds: false,
      clock_zone: true,
      palette: "WOPR",
      display: "CRT",
      scan_opacity: 34,
      scan_size: 3,
      glow_map: 33,
      glow_traffic: 33,
      glow_text: 33,
      aa: "ON",
      burn_in: 19,
      fps_max: 60,
      poll_secs: 15,
      motion: "GLIDE",
      view_ease: "QUICK",
      zoom_speed: 100,
      lamps: false,
      teletype: false,
      // Traffic
      range_nm: 40,
      tag_fields: ["CALLSIGN", "ALT"],
      box_items: [],
      box_fill: 70,
      box_pad: 4,
      box_border: 50,
      box_width: 1,
      map: {
        COAST: { show: true, alpha: 100, line: "SOLID", width: 18 },
        LAKE: { show: true, alpha: 75, line: "SOLID", width: 12 },
        RIVER: { show: true, alpha: 50, line: "SOLID", width: 10 },
        COUNTRY: { show: true, alpha: 90, line: "DASH", width: 12 },
        STATE: { show: true, alpha: 55, line: "SOLID", width: 10 },
        AIRWAY: { show: true, alpha: 70, line: "DASH", width: 12 },
        CLASS_B: { show: true, alpha: 90, line: "DASH", width: 14 },
        CLASS_C: { show: true, alpha: 80, line: "DASH", width: 13 },
        CLASS_D: { show: true, alpha: 45, line: "DOT", width: 10 },
        RUNWAYS: { show: true, alpha: 100, width: 16 },
        RINGS: { show: true, alpha: 35, line: "SOLID", width: 10, label: 12 },
        HOME: { show: true, alpha: 100, width: 18, label: 30 },
        AIRPORTS: { show: true, alpha: 85, width: 13, label: 13 },
        NAVAIDS: { show: true, alpha: 85, width: 13, label: 13 },
        CITIES: { show: true, alpha: 85, width: 13, label: 13 },
        PEAKS: { show: true, alpha: 85, width: 13, label: 13 },
        STATE_NAMES: { show: true, alpha: 100, label: 14 },
      },
      label_min: 9,
      label_max: 26,
      tag_px: 16,
      follow_nm: 10,
      info_box: true,
      tail_secs: 180,
      tail_alpha: 95,
      tail_alpha_min: 35,
      tail_alpha_max: 95,
      tail_gs_low: 40,
      tail_gs_high: 250,
      ground_mode: "FADE",
      ground_gs: 5,
      ground_alt: 0,
      ground_min: 2,
      ground_alpha: 25,
      // Tracks
      track_cols: ["CALLSIGN", "TYPE", "ALT", "GS", "TRK", "DIST", "SQWK"],
      track_sort: "DIST",
      track_desc: false,
      sort_floor: 40,
      tracks_open: true,
      tracks_pct: 24,
      // Frequencies
      short_names: true,
    },
    log: [],
    history: new Map(), // ident -> { samples: Float32Array, next: number }
    radar: null, // the last aircraft frame
    radarAt: 0, // performance.now() when it arrived
    trails: new Map(), // hex -> [{ lat, lon }], oldest first
  };
  const listeners = new Set();
  const emit = (kind, detail) => { for (const fn of listeners) fn(kind, detail, state); };

  function historyFor(ident) {
    let h = state.history.get(ident);
    if (!h) {
      h = { samples: new Float32Array(HISTORY).fill(SILENT), next: 0 };
      state.history.set(ident, h);
    }
    return h;
  }

  // Each poll adds the aircraft's reported position to its trail; the page
  // dead reckons from there between polls. An aircraft that drops out of
  // the frame loses its trail.
  function takeRadar(frame) {
    state.radar = frame;
    state.radarAt = performance.now();
    const seen = new Set();
    for (const ac of frame.ac) {
      seen.add(ac.hex);
      const trail = state.trails.get(ac.hex) || [];
      const last = trail[trail.length - 1];
      if (!last || last.lat !== ac.lat || last.lon !== ac.lon) trail.push({ lat: ac.lat, lon: ac.lon });
      if (trail.length > TRAIL) trail.shift();
      state.trails.set(ac.hex, trail);
    }
    for (const hex of [...state.trails.keys()]) if (!seen.has(hex)) state.trails.delete(hex);
  }

  function apply(frame) {
    switch (frame.t) {
      case "snapshot":
        if (!state.airport || !frame.airport || state.airport.icao !== frame.airport.icao) state.trails.clear();
        state.airport = frame.airport;
        state.loading = frame.loading;
        state.feeds = new Map(frame.feeds.map((f) => [f.ident, f]));
        state.order = frame.feeds.map((f) => f.ident);
        state.volume = frame.volume;
        state.audioOk = frame.audio_ok;
        state.prefs = { ...state.prefs, ...(frame.prefs || {}) };
        state.log = frame.log.slice(-200);
        if (frame.radar) takeRadar(frame.radar);
        for (const ident of [...state.history.keys()]) {
          if (!state.feeds.has(ident)) state.history.delete(ident);
        }
        emit("all");
        break;
      case "feed":
        state.feeds.set(frame.feed.ident, frame.feed);
        emit("feed", frame.feed.ident);
        break;
      case "added":
        state.feeds.set(frame.feed.ident, frame.feed);
        if (!state.order.includes(frame.feed.ident)) state.order.push(frame.feed.ident);
        emit("order");
        break;
      case "order":
        state.order = frame.idents.filter((ident) => state.feeds.has(ident));
        emit("order");
        break;
      case "levels":
        for (const [ident, db] of Object.entries(frame.v)) {
          const h = historyFor(ident);
          h.samples[h.next] = db;
          h.next = (h.next + 1) % HISTORY;
        }
        emit("levels");
        break;
      case "chatter":
        for (const [ident, value] of Object.entries(frame.v)) {
          const feed = state.feeds.get(ident);
          if (feed) feed.chatter = value;
        }
        emit("chatter");
        break;
      case "aircraft":
        takeRadar(frame);
        emit("aircraft");
        break;
      case "volume":
        state.volume = frame.value;
        emit("volume");
        break;
      case "prefs": {
        const { t, ...prefs } = frame;
        state.prefs = { ...state.prefs, ...prefs };
        emit("prefs");
        break;
      }
      case "message":
        state.log.push({ z: frame.z, text: frame.text });
        if (state.log.length > 200) state.log.shift();
        emit("message", { z: frame.z, text: frame.text });
        break;
      case "error":
        emit("message", { z: "PAGE", text: "error: " + frame.text, page: true });
        break;
    }
  }

  return {
    state,
    apply,
    historyFor,
    setConnected(value) { state.connected = value; emit("connection"); },
    setShutdown() { state.shutdown = true; emit("connection"); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
