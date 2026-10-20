// Which aircraft is focused (spec, Visual language: click an aircraft to
// focus it). Belongs to the page, not the server: each tab has its own.
// The radar and the tracks table both read and set it.

let current = null;
const listeners = new Set();

export const focus = {
  get hex() { return current; },
  toggle(hex) { this.set(current === hex ? null : hex); },
  set(hex) {
    if (hex === current) return;
    current = hex;
    for (const fn of listeners) fn(current);
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};
