// The teletype: one line per message, newest at the bottom. A new line types
// itself out within 400 ms; with reduced motion it appears at once. The
// snapshot's history is drawn instantly.

import { reducedMotion } from "./theme.js";

const CAP = 200;
const TYPE_MS = 400;

function kindOf(text) {
  if (/^error|fail|could not|403|offline/i.test(text)) return "alarm";
  if (/reconnect|retry|warn/i.test(text)) return "warn";
  return "";
}

export function mountLog(node, store) {
  const queue = [];
  let typing = false;

  function line(entry) {
    const row = document.createElement("div");
    row.className = `log-line ${entry.page ? "alarm" : kindOf(entry.text)}`.trim();
    const z = document.createElement("span");
    z.className = "log-z";
    z.textContent = entry.z;
    const text = document.createElement("span");
    text.className = "log-text";
    row.append(z, text);
    return { row, text };
  }

  function stick(fn) {
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    fn();
    while (node.childElementCount > CAP) node.firstElementChild.remove();
    if (atBottom) node.scrollTop = node.scrollHeight;
  }

  function drawAll() {
    queue.length = 0;
    stick(() => {
      node.replaceChildren();
      for (const entry of store.state.log) {
        const { row, text } = line(entry);
        text.textContent = entry.text.toUpperCase();
        node.append(row);
      }
    });
    node.scrollTop = node.scrollHeight;
  }

  function next() {
    const entry = queue.shift();
    if (!entry) { typing = false; return; }
    typing = true;
    const { row, text } = line(entry);
    const full = entry.text.toUpperCase();
    stick(() => node.append(row));
    if (reducedMotion() || queue.length > 3) {
      text.textContent = full;
      next();
      return;
    }
    const start = performance.now();
    const step = (now) => {
      const shown = Math.min(full.length, Math.ceil(((now - start) / TYPE_MS) * full.length));
      text.textContent = full.slice(0, shown);
      if (shown < full.length) requestAnimationFrame(step);
      else next();
    };
    requestAnimationFrame(step);
  }

  store.subscribe((kind, detail) => {
    if (kind === "all") drawAll();
    else if (kind === "message") { queue.push(detail); if (!typing) next(); }
  });

  return {
    // A line from the page itself, such as a failed request.
    say(text) { queue.push({ z: "PAGE", text, page: true }); if (!typing) next(); },
  };
}
