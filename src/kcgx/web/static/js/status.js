// The status screen: the airport and two clocks. Zulu is HHMMZ; local is the
// viewer's own clock with its zone, since the airport dataset has no zones.
// The prefs set the local clock's hours (clock_24h: 15:07 or 3:07 PM),
// add seconds to both (clock_seconds: 1507:42Z, 15:07:42) and name the zone
// or not (clock_zone).

const pad = (n) => String(n).padStart(2, "0");
const ZONE = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" });

// Both clocks as the prefs have them, each in four parts: the hours and
// minutes, the seconds (":SS", or empty), AM or PM (" AM", or empty) and
// the rest ("Z", " PST", or empty).
export function clockParts(now, { clock_24h: h24, clock_seconds: seconds, clock_zone: named }) {
  const secs = (n) => (seconds ? `:${pad(n)}` : "");
  const zulu = [`${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}`, secs(now.getUTCSeconds()), "", "Z"];
  const hours = now.getHours();
  const time = h24 ? `${pad(hours)}:${pad(now.getMinutes())}` : `${hours % 12 || 12}:${pad(now.getMinutes())}`;
  const half = h24 ? "" : hours < 12 ? " AM" : " PM";
  // The zone's name now, not at mount: it changes with daylight saving.
  const zone = named ? ZONE.formatToParts(now).find((p) => p.type === "timeZoneName") : null;
  return [zulu, [time, secs(now.getSeconds()), half, zone ? ` ${zone.value}` : ""]];
}

// A clock's parts into its node: the seconds and AM/PM in spans of their
// own, set smaller than the minutes (cockpit.css), so the longest clocks
// still fit beside the ICAO. The 24-hour clocks without seconds are plain
// text, as they always were.
function show(node, [main, secs, half, rest]) {
  const text = main + secs + half + rest;
  if (node.textContent === text) return;
  const small = (className, content) => {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = content;
    return span;
  };
  const parts = [main];
  if (secs) parts.push(small("secs", secs));
  if (half) parts.push(small("half", half));
  if (rest) parts.push(rest);
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
