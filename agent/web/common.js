// Formatting and rendering helpers shared by the dashboard and the deep-dive report page.
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 3) => v == null ? "–" : Number(v).toFixed(d);
const pct = (v) => v == null ? "–" : (v * 100).toFixed(1) + "%";
const big = (v) => {
  if (v == null) return "–";
  const a = Math.abs(v);
  return a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(1) + "M" : a >= 1e3 ? (v / 1e3).toFixed(0) + "K" : String(v);
};
const sign = (v) => (v > 0 ? "+" : "") + v.toFixed(2) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cls = { "+": "p", "-": "m", "=": "e" };
const chg = (v) => v == null ? "–" : `<span class="${v >= 0 ? "up" : "down"}">${sign(v)}</span>`;
const bullets = (xs) => xs && xs.length ? `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
const reasons = (list) => `<ul class="reasons">${list.map(([k, t]) => `<li class="${cls[k]}">${esc(t)}</li>`).join("")}</ul>`;
const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? esc(u) : "#";
const newsList = (items) => items && items.length
  ? `<ul class="news">${items.map((n) => `<li><a href="${safeUrl(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
      <div class="sub">${esc(n.source)} · ${esc(n.date)}</div></li>`).join("")}</ul>`
  : `<p class="empty">No headlines found.</p>`;

// Stock data without the bulky chart arrays, for sending to the AI chat
const forAI = (s) => {
  const { candles, sma50, sma200, ...rest } = s;
  return rest;
};

function drawChart(el, s) {
  if (!window.LightweightCharts) { el.textContent = "Chart library failed to load (offline?)."; return; }
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: v("--muted") },
    grid: { vertLines: { visible: false }, horzLines: { color: v("--line") } },
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
  });
  chart.addCandlestickSeries({
    upColor: v("--pos"), downColor: v("--neg"), wickUpColor: v("--pos"), wickDownColor: v("--neg"),
    borderVisible: false, priceFormat: { type: "price", precision: 3, minMove: 0.005 },
  }).setData(s.candles);
  chart.addLineSeries({ color: "#f0a020", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }).setData(s.sma50);
  chart.addLineSeries({ color: "#7b61ff", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }).setData(s.sma200);
  const from = s.candles[Math.max(0, s.candles.length - 260)].time;
  chart.timeScale().setVisibleRange({ from, to: s.candles[s.candles.length - 1].time });
}

const CHART_LEGEND = `<div class="legend"><span><i style="background:#f0a020"></i>50-day avg</span><span><i style="background:#7b61ff"></i>200-day avg</span></div>`;
