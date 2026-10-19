// The lamp bar (spec, Visual language): one lamp per feed, lit in its state
// colour (cyan live, amber reconnecting, red offline, dark parked), then the
// system lamps. RADAR and EMERG stay dark until phase D.

const SHORT = [
  [/clearance delivery/i, "DEL"], [/delivery/i, "DEL"], [/approach/i, "APP"], [/departure/i, "DEP"],
  [/tower/i, "TWR"], [/ground/i, "GND"], [/atis/i, "ATIS"], [/center|centre/i, "CTR"],
  [/emergency|guard/i, "GRD"], [/ramp/i, "RAMP"],
];

export function shortLabel(name) {
  for (const [pattern, short] of SHORT) if (pattern.test(name)) return short;
  return name.replace(/^[A-Z]{3,4}\s+/, "").slice(0, 4).toUpperCase();
}

const LIT = { live: "live", starting: "warn", reconnecting: "warn", offline: "fault" };

function lamp(label, colour, title) {
  const on = Boolean(colour);
  const node = document.createElement("span");
  node.className = `lamp ${on ? `on ${colour}` : ""}`.trim();
  const light = document.createElement("span");
  light.className = "lamp-light";
  const text = document.createElement("span");
  text.className = "lamp-label";
  text.textContent = label;
  node.append(light, text);
  node.title = title;
  node.setAttribute("aria-label", `${title}: ${on ? "on" : "off"}`);
  return node;
}

export function mountLamps(row, store) {
  function render() {
    const { state } = store;
    const lamps = [];
    const seen = new Map();
    for (const ident of state.order) {
      const feed = state.feeds.get(ident);
      if (!feed) continue;
      let label = shortLabel(feed.name);
      const count = (seen.get(label) || 0) + 1;
      seen.set(label, count);
      if (count > 1) label = `${label}${count}`;
      const title = `${feed.name}, ${feed.state}${feed.muted ? ", muted" : ""}`;
      lamps.push(lamp(label, LIT[feed.state], title));
    }
    const gap = document.createElement("span");
    gap.className = "lamp-gap";
    lamps.push(
      gap,
      lamp("RADAR", null, "Radar, arrives in phase D"),
      lamp("SERVER", state.connected ? "live" : "fault", "Connection to the KCGX server"),
      lamp("AUDIO", state.connected ? (state.audioOk ? "live" : "fault") : null, "Audio output on the server"),
      lamp("EMERG", null, "Emergency squawk, arrives in phase D"),
    );
    row.replaceChildren(...lamps);
  }
  store.subscribe((kind) => {
    if (kind !== "levels" && kind !== "chatter" && kind !== "message" && kind !== "volume") render();
  });
  render();
}
