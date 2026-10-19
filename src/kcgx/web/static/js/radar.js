// The radar placeholder until phase D: range rings every 10 nm out to 40,
// the airport in pink at the centre, sized to fill its pane. The 40 nm ring
// fits the shorter side; the longer side shows more of the map.

import { colours, glowBlur } from "./theme.js";

const RINGS_NM = [10, 20, 30, 40];

export function mountRadar(canvas, store) {
  let dirty = true;

  function draw() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext("2d");
    const c = colours();
    const cx = width / 2;
    const cy = height / 2;
    const perNm = Math.max(0, Math.min(width, height) / 2 - 18 * ratio) / 40;
    ctx.clearRect(0, 0, width, height);

    ctx.save();
    ctx.strokeStyle = c.dim;
    ctx.lineWidth = ratio;
    ctx.setLineDash([2 * ratio, 6 * ratio]);
    ctx.beginPath();
    ctx.moveTo(0, cy); ctx.lineTo(width, cy);
    ctx.moveTo(cx, 0); ctx.lineTo(cx, height);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = c.cyan;
    ctx.shadowColor = c.cyan;
    ctx.shadowBlur = glowBlur() * ratio;
    ctx.lineWidth = ratio;
    ctx.fillStyle = c.dim;
    ctx.font = `${11 * ratio}px "Share Tech Mono", monospace`;
    ctx.textAlign = "left";
    for (const nm of RINGS_NM) {
      ctx.globalAlpha = nm === 40 ? 0.9 : 0.45;
      ctx.beginPath();
      ctx.arc(cx, cy, nm * perNm, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(`${nm}`, cx + nm * perNm * Math.SQRT1_2 + 4 * ratio, cy - nm * perNm * Math.SQRT1_2 - 4 * ratio);
    }
    ctx.restore();

    const airport = store.state.airport;
    ctx.save();
    ctx.strokeStyle = c.pink;
    ctx.fillStyle = c.pink;
    ctx.shadowColor = c.pink;
    ctx.shadowBlur = glowBlur() * ratio;
    ctx.lineWidth = 1.5 * ratio;
    ctx.beginPath();
    ctx.arc(cx, cy, 6 * ratio, 0, Math.PI * 2);
    ctx.stroke();
    if (airport) {
      ctx.font = `${13 * ratio}px "Share Tech Mono", monospace`;
      ctx.fillText(airport.icao, cx + 10 * ratio, cy + 18 * ratio);
    }
    ctx.restore();
  }

  function frame() {
    if (dirty) { dirty = false; draw(); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  new ResizeObserver(() => { dirty = true; }).observe(canvas);
  store.subscribe((kind) => { if (kind === "all" || kind === "prefs") dirty = true; });
  return { redraw() { dirty = true; } };
}
