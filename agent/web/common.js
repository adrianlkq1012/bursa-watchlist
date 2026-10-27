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

// lines: horizontal price lines, e.g. [{ price, color, title, dashed }]
// intraday: candle times are unix seconds; shows clock times and a VWAP line if given
function drawChart(el, s, { lines = [], intraday = false, vwap = null, show = 260 } = {}) {
  el.innerHTML = "";
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
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: intraday },
  });
  const series = chart.addCandlestickSeries({
    upColor: v("--pos"), downColor: v("--neg"), wickUpColor: v("--pos"), wickDownColor: v("--neg"),
    borderVisible: false, priceFormat: { type: "price", precision: 3, minMove: 0.005 },
  });
  series.setData(s.candles);
  const line = (data, color) => data.length && chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }).setData(data);
  line(s.sma50, "#f0a020");
  line(s.sma200, "#7b61ff");
  if (vwap) line(vwap, "#2bb3c0");
  for (const l of lines) {
    if (l.price == null) continue;
    series.createPriceLine({ price: l.price, color: l.color, lineWidth: l.dashed ? 1 : 2,
      lineStyle: l.dashed ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true, title: l.title || "" });
  }
  // Zoom to the last `show` bars once the chart has its size (it ignores this before layout)
  const n = s.candles.length;
  requestAnimationFrame(() => chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - show), to: n + 2 }));
  return { chart, series };
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

// ---- Live prices ----
// Bursa trades Mon–Fri 9:00–12:30 and 14:30–17:00 Malaysia time (public holidays not checked)
function marketOpen(now = new Date()) {
  const myt = new Date(now.getTime() + 8 * 3600e3);
  const day = myt.getUTCDay(), mins = myt.getUTCHours() * 60 + myt.getUTCMinutes();
  return day >= 1 && day <= 5 && ((mins >= 540 && mins <= 750) || (mins >= 870 && mins <= 1020));
}

// "Last trade 10:42am (about 15 min delayed)"
function tradeTimeLabel(unix) {
  if (!unix) return "";
  const d = new Date(unix * 1000);
  const t = d.toLocaleTimeString("en-MY", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kuala_Lumpur" });
  const day = d.toLocaleDateString("en-MY", { day: "numeric", month: "short", timeZone: "Asia/Kuala_Lumpur" });
  const today = new Date().toLocaleDateString("en-MY", { day: "numeric", month: "short", timeZone: "Asia/Kuala_Lumpur" });
  return marketOpen()
    ? `Last trade ${t} · Yahoo data, about 15 min delayed · updates every minute`
    : `Market closed · last trade ${day === today ? "" : day + " "}${t}`;
}

// Calls onUpdate({code: quote}) now and then every minute while the market is open.
// codes may be a function, so the list can change without starting another timer.
function watchPrices(codes, onUpdate) {
  const list = () => (typeof codes === "function" ? codes() : codes);
  const tick = () => list().length && relay(`/quote/${list().join(",")}`).then(onUpdate).catch(() => {});
  tick();
  setInterval(() => { if (marketOpen() && !document.hidden) tick(); }, 60e3);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && marketOpen()) tick(); });
}

// Refresh the price cells (data-px / data-chg) every minute while the market is open
let liveCodes = null;
function liveCells(codes) {
  const first = liveCodes === null;
  liveCodes = codes;
  if (!first) { relay(`/quote/${codes.join(",")}`).then(updateCells).catch(() => {}); return; }
  watchPrices(() => liveCodes, updateCells);
}
function updateCells(q) {
  for (const [code, x] of Object.entries(q)) {
    document.querySelectorAll(`[data-px="${code}"]`).forEach((el) => {
      const v = (el.dataset.prefix || "") + fmt(x.price);
      if (el.textContent !== v) { el.textContent = v; el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
    });
    document.querySelectorAll(`[data-chg="${code}"]`).forEach((el) => { el.innerHTML = chg(x.change_pct); el.className = ""; });
  }
  const any = Object.values(q)[0];
  document.querySelectorAll(".live").forEach((el) => { el.textContent = tradeTimeLabel(any?.time); el.classList.toggle("on", marketOpen()); });
}

// ---- Watchlist ----
// The owner (passcode saved on this device) edits the shared list stored on the relay, so it
// syncs across their devices and drives the daily AI briefs. Everyone else keeps their own
// list on their device, starting empty.
const Watch = (() => {
  const LIST = "watchlist_codes", OWNER = "owner_key";
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const lsSet = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} };
  let codes = null, claimed = true, loading = null;
  const listeners = [];

  const isOwner = () => !!lsGet(OWNER);

  function load(force = false) {
    if (codes && !force) return Promise.resolve(codes);
    return loading = loading && !force ? loading : relay("/watchlist").catch(() => ({ codes: [], claimed: true })).then((srv) => {
      claimed = srv.claimed;
      const mine = lsGet(LIST);
      if (isOwner()) codes = srv.codes;
      else if (mine) codes = JSON.parse(mine);
      else codes = [];
      loading = null;
      return codes;
    });
  }

  async function save(next) {
    const prev = codes;
    codes = next;
    notify();
    if (!isOwner()) { lsSet(LIST, JSON.stringify(next)); return; }
    try {
      codes = (await relaySend("PUT", "/watchlist", { codes: next }, { "X-Owner-Key": lsGet(OWNER) })).codes;
    } catch (e) {
      codes = prev;
      if (e.status === 403) { lsSet(OWNER, null); alert("Your saved passcode no longer works. Unlock again on the My Watchlist page."); }
      else alert(`Couldn't save your watchlist (${e.message}). Try again in a moment.`);
    }
    notify();
  }

  async function toggle(code) {
    const list = await load();
    save(list.includes(code) ? list.filter((c) => c !== code) : [...list, code]);
  }

  function notify() {
    document.querySelectorAll("[data-star]").forEach(paint);
    listeners.forEach((f) => f(codes));
  }

  function paint(el) {
    const on = !!codes?.includes(el.dataset.star);
    el.classList.toggle("on", on);
    el.setAttribute("aria-pressed", on);
    el.title = on ? "Remove from My Watchlist" : "Add to My Watchlist";
    el.innerHTML = `${on ? "★" : "☆"}<span>${on ? "In watchlist" : "Watch"}</span>`;
  }

  // One listener for every star on the page, including ones rendered later
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-star]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    toggle(b.dataset.star);
  });

  return {
    load, toggle, isOwner, onChange: (f) => listeners.push(f),
    claimed: () => claimed,
    has: (code) => !!codes?.includes(code),
    star: (code) => `<button class="star" data-star="${esc(code)}" type="button"></button>`,
    paintAll: () => load().then(() => document.querySelectorAll("[data-star]").forEach(paint)),
    async unlock(pass) { await relaySend("POST", "/watchlist/verify", { passcode: pass }); lsSet(OWNER, pass); await load(true); notify(); },
    async claim(pass) { await relaySend("POST", "/watchlist/claim", { passcode: pass }); lsSet(OWNER, pass); await load(true); notify(); },
    lock() { lsSet(OWNER, null); return load(true).then(notify); },
    clear: () => save([]),
  };
})();
