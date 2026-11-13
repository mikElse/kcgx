// The status screen: the airport and two clocks. Zulu is HHMMZ; local is the
// viewer's own clock with its zone, since the airport dataset has no zones.
// The prefs set the local clock's hours (clock_24h: 15:07 or 3:07 PM),
// add seconds to both (clock_seconds: 1507:42Z, 15:07:42) and name the zone
// or not (clock_zone).

const pad = (n) => String(n).padStart(2, "0");
const ZONE = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" });

// Both clocks as the prefs have them, each in three parts: the hours and
// minutes, the seconds (":SS", or empty) and what follows ("Z", " PM PST").
export function clockParts(now, { clock_24h: h24, clock_seconds: seconds, clock_zone: named }) {
  const secs = (n) => (seconds ? `:${pad(n)}` : "");
  const zulu = [`${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}`, secs(now.getUTCSeconds()), "Z"];
  const hours = now.getHours();
  const time = h24 ? `${pad(hours)}:${pad(now.getMinutes())}` : `${hours % 12 || 12}:${pad(now.getMinutes())}`;
  // The zone's name now, not at mount: it changes with daylight saving.
  const zone = named ? ZONE.formatToParts(now).find((p) => p.type === "timeZoneName") : null;
  const after = [h24 ? "" : hours < 12 ? "AM" : "PM", zone ? zone.value : ""].filter(Boolean).join(" ");
  return [zulu, [time, secs(now.getSeconds()), after ? ` ${after}` : ""]];
}

// A clock's parts into its node: the seconds in a span of their own, set
// smaller than the minutes (cockpit.css), so the longest clocks still fit
// beside the ICAO.
function show(node, [main, secs, after]) {
  const text = main + secs + after;
  if (node.textContent === text) return;
  const parts = [main];
  if (secs) {
    const span = document.createElement("span");
    span.className = "secs";
    span.textContent = secs;
    parts.push(span);
  }
  if (after) parts.push(after);
  node.replaceChildren(...parts);
}

export function mountStatus(nodes, store) {
  // Each second as it turns, so that the seconds keep time with the wall.
  let timer = 0;
  function tick() {
    clearTimeout(timer);
    const now = new Date();
    const [zulu, local] = clockParts(now, store.state.prefs);
    show(nodes.zulu, zulu);
    show(nodes.local, local);
    timer = setTimeout(tick, 1000 - (now.getTime() % 1000) + 5);
  }

  function render() {
    const airport = store.state.airport;
    if (!airport) return;
    nodes.icao.textContent = airport.icao;
    nodes.name.textContent = (airport.name || "UNKNOWN AIRPORT").toUpperCase();
    nodes.where.textContent = (airport.where || "").toUpperCase();
    document.title = `KCGX ${airport.icao}`;
  }

  tick();
  store.subscribe((kind) => {
    if (kind === "all") render();
    if (kind === "all" || kind === "prefs") tick();
  });
  render();
}
