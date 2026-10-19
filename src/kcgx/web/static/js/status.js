// The status screen: the airport and two clocks. Zulu is HHMMZ; local is the
// viewer's own clock with its zone, since the airport dataset has no zones.

const pad = (n) => String(n).padStart(2, "0");

export function mountStatus(nodes, store) {
  const zone = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
    .formatToParts(new Date()).find((p) => p.type === "timeZoneName");

  function tick() {
    const now = new Date();
    nodes.zulu.textContent = `${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}Z`;
    nodes.local.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())} ${zone ? zone.value : ""}`.trim();
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
  setInterval(tick, 1000);
  store.subscribe((kind) => { if (kind === "all") render(); });
  render();
}
