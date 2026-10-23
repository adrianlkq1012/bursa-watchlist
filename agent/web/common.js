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
  const { candles, sma50, sma200, volumes, ...rest } = s;
  return rest;
};

// All-stock pages store chart data as compact arrays; the watchlist uses objects
const asCandles = (xs) => (xs || []).map((c) => Array.isArray(c) ? { time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] } : c);
const asLine = (xs) => (xs || []).map((p) => Array.isArray(p) ? { time: p[0], value: p[1] } : p);

function drawChart(el, s) {
  if (!window.LightweightCharts) { el.textContent = "Chart library failed to load (offline?)."; return; }
  const candles = asCandles(s.candles);
  if (!candles.length) { el.textContent = "No price history available."; return; }
  s = { candles, sma50: asLine(s.sma50), sma200: asLine(s.sma200) };
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

// Top navigation with a stock search box, shared by every page
function mountNav(active) {
  const nav = document.createElement("nav");
  nav.className = "topnav";
  nav.innerHTML = `
    <a class="brand" href="./">Bursa Research</a>
    <a class="${active === "watchlist" ? "on" : ""}" href="watchlist.html">My Watchlist</a>
    ${active === "home" ? "" : `<div class="nav-search"></div>`}`;
  document.body.prepend(nav);
  const box = nav.querySelector(".nav-search");
  if (box) mountSearch(box, { compact: true });
}

// Search any Bursa stock by code, short name or company name
function mountSearch(el, { compact = false, autofocus = false } = {}) {
  el.classList.add("search");
  el.innerHTML = `<input type="search" placeholder="${compact ? "Search stocks…" : "Search any Bursa stock: name or code, e.g. Maybank, 5347, Inari"}"
      autocomplete="off" spellcheck="false" aria-label="Search stocks"><div class="results" hidden></div>`;
  const input = el.querySelector("input"), box = el.querySelector(".results");
  let hits = [], sel = 0;
  const go = (code) => { location.href = `stock.html?code=${encodeURIComponent(code)}`; };

  function score(r, q) {
    const s = r.s.toLowerCase(), n = r.n.toLowerCase();
    if (r.c === q || s === q) return 0;
    if (r.c.startsWith(q) || s.startsWith(q)) return 1;
    if (n.startsWith(q)) return 2;
    if (n.split(/\s+/).some((w) => w.startsWith(q))) return 3;
    if (s.includes(q) || n.includes(q)) return 4;
    return -1;
  }
  function render() {
    box.hidden = !hits.length;
    box.innerHTML = hits.map((r, i) => `
      <a href="stock.html?code=${r.c}" class="${i === sel ? "sel" : ""}">
        <span><b>${esc(r.s)}</b> <span class="sub">${r.c}</span><br><span class="sub">${esc(r.n)}</span></span>
        <span class="r sub">${esc(r.sec || "")}</span></a>`).join("");
  }
  let timer, latest = "";
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim().toLowerCase();
    latest = q;
    if (!q) { hits = []; render(); return; }
    timer = setTimeout(async () => {
      const found = await relay(`/search?q=${encodeURIComponent(q)}`).catch(() => []);
      if (q !== latest) return;
      hits = found.map((r) => [score(r, q), r]).sort((a, b) => (a[0] < 0) - (b[0] < 0) || a[0] - b[0]).slice(0, 8).map(([, r]) => r);
      // A 4-digit code always works even if search doesn't know it
      if (/^\d{4}$/.test(q) && !hits.some((r) => r.c === q)) hits.unshift({ c: q, s: q, n: "Open stock code " + q });
      sel = 0; render();
    }, 250);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, hits.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[sel]) go(hits[sel].c);
    else if (e.key === "Escape") { hits = []; render(); }
  });
  document.addEventListener("click", (e) => { if (!el.contains(e.target)) { hits = []; render(); } });
  if (autofocus && matchMedia("(min-width: 700px)").matches) input.focus();
}
