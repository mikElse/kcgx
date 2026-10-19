// One WebSocket to the server, reconnected with backoff (spec, Error
// handling: "WebSocket drops"). Nothing is lost while it is down: the server
// holds all state, and the first frame after a reconnect is a snapshot.

const BACKOFF_MS = [500, 1000, 2000, 4000, 5000];

export function connect(store) {
  let socket = null;
  let attempt = 0;
  let stopped = false;

  function open() {
    if (stopped) return;
    socket = new WebSocket(`ws://${location.host}/ws`);
    socket.addEventListener("open", () => {
      attempt = 0;
      store.setConnected(true);
    });
    socket.addEventListener("message", (event) => {
      let frame;
      try { frame = JSON.parse(event.data); } catch { return; }
      store.apply(frame);
    });
    socket.addEventListener("close", () => {
      store.setConnected(false);
      if (stopped) return;
      const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      setTimeout(open, wait);
    });
  }

  open();

  return {
    send(message) {
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
    },
    stop() {
      stopped = true;
      if (socket) socket.close();
    },
  };
}
