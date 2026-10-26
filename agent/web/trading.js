// Rule-based trading setups: support/resistance, trend, and entry / stop-loss /
// take-profit plans for swing trades (daily bars) and day trades (15-minute bars).
// Long-only: short selling on Bursa is restricted for most retail investors.
// Candles are [time, open, high, low, close] arrays.

// Bursa price steps ("tick sizes")
function tickSize(p) {
  return p < 1 ? 0.005 : p < 10 ? 0.01 : p < 100 ? 0.02 : 0.1;
}
function toTick(p, dir = "round") {
  if (p == null || !isFinite(p)) return null;
  const t = tickSize(p), x = p / t;
  const n = dir === "up" ? Math.ceil(x - 1e-9) : dir === "down" ? Math.floor(x + 1e-9) : Math.round(x);
  return +(n * t).toFixed(3);
}

function atr(candles, n = 14) {
  const tr = candles.map((c, i) => {
    if (!i) return c[2] - c[3];
    const pc = candles[i - 1][4];
    return Math.max(c[2] - c[3], Math.abs(c[2] - pc), Math.abs(c[3] - pc));
  });
  let a = tr.slice(0, n).reduce((x, y) => x + y, 0) / Math.min(n, tr.length);
  for (let i = n; i < tr.length; i++) a = (a * (n - 1) + tr[i]) / n; // Wilder smoothing
  return a;
}

const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;

// Support/resistance: swing highs and lows (turning points), grouped when they sit
// within ~half an ATR of each other. More touches = stronger level.
function levels(candles, { k = 5, lookback = 250 } = {}) {
  const cs = candles.slice(-lookback), a = atr(cs), pivots = [];
  for (let i = k; i < cs.length - k; i++) {
    const win = cs.slice(i - k, i + k + 1);
    if (cs[i][2] === Math.max(...win.map((c) => c[2]))) pivots.push({ p: cs[i][2], t: cs[i][0], i });
    if (cs[i][3] === Math.min(...win.map((c) => c[3]))) pivots.push({ p: cs[i][3], t: cs[i][0], i });
  }
  pivots.sort((x, y) => x.p - y.p);
  const groups = [];
  for (const pv of pivots) {
    const g = groups[groups.length - 1];
    if (g && pv.p - g.ps[g.ps.length - 1].p <= a * 0.5) g.ps.push(pv);
    else groups.push({ ps: [pv] });
  }
  const close = cs[cs.length - 1][4];
  return groups.map((g) => ({
    price: toTick(avg(g.ps.map((x) => x.p))),
    touches: g.ps.length,
    last: g.ps.reduce((m, x) => (x.i > m.i ? x : m)).t,
    recency: Math.max(...g.ps.map((x) => x.i)) / cs.length,
  }))
    // keep levels touched twice, or once recently
    .filter((l) => l.touches >= 2 || l.recency > 0.8)
    .map((l) => ({ ...l, type: l.price < close ? "support" : "resistance" }));
}

function nearest(lv, price, type) {
  const xs = lv.filter((l) => l.type === type).sort((a, b) => type === "support" ? b.price - a.price : a.price - b.price);
  return xs;
}

// minRisk stops a stop-loss sitting so close to entry that normal noise would hit it
function plan({ name, entry, stop, tp1, tp2, why, bias, kind, minRisk = 0 }) {
  entry = toTick(entry, "up");
  stop = toTick(Math.min(stop, entry - minRisk, entry - tickSize(entry)), "down");
  const risk = entry - stop;
  // A level far above (e.g. a pre-crash price) is unrealistic as a first target: take 2R first
  if (tp1 != null && tp1 > entry + 4 * risk) { tp2 = tp2 ?? tp1; tp1 = entry + 2 * risk; }
  tp1 = toTick(Math.max(tp1 ?? entry + 2 * risk, entry + tickSize(entry)), "down");
  tp2 = toTick(Math.max(tp2 ?? entry + 3 * risk, tp1 + tickSize(tp1)), "down");
  const rr = (tp1 - entry) / risk;
  return { name, kind, bias, entry, stop, tp1, tp2, rr, why, good: rr >= 1.5 };
}

// Swing trades: hold for days to weeks, using daily bars
function swingSetup(candles, volumes) {
  const close = candles.map((c) => c[4]), n = close.length, last = close[n - 1];
  const sma = (k) => avg(close.slice(-k));
  const s20 = sma(20), s50 = sma(50), s200 = n >= 200 ? sma(200) : null;
  const s50prev = avg(close.slice(-60, -10));
  const a = atr(candles), lv = levels(candles);
  const sup = nearest(lv, last, "support"), res = nearest(lv, last, "resistance");
  const S1 = sup[0]?.price ?? toTick(Math.min(...candles.slice(-60).map((c) => c[3]))), S2 = sup[1]?.price;
  const R1 = res[0]?.price ?? toTick(Math.max(...candles.slice(-60).map((c) => c[2]))), R2 = res[1]?.price;
  const vol20 = avg(volumes.slice(-21, -1)), volRatio = vol20 ? volumes[n - 1] / vol20 : 1;

  const up = last > s50 && s50 > s50prev && (s200 == null || last > s200);
  const down = last < s50 && s50 < s50prev && (s200 == null || last < s200);
  const trend = up ? "Uptrend" : down ? "Downtrend" : "Sideways";
  const brokeOut = lv.some((l) => l.price < last && l.price > close[n - 4] && l.touches >= 2);
  const fx = (v) => fmt(v, v < 1 ? 3 : 2);

  let p;
  if (up && brokeOut && volRatio >= 1.5) {
    const lvl = lv.filter((l) => l.price < last && l.price > close[n - 4]).pop().price;
    p = plan({ kind: "Breakout", bias: "Bullish", name: "Breakout buy", minRisk: 0.5 * a,
      entry: last, stop: lvl - a, tp1: R1, tp2: R2,
      why: `Price just closed above resistance at ${fx(lvl)} on ${volRatio.toFixed(1)}× normal volume, in an uptrend. Old resistance often becomes new support; the stop sits one ATR below it.` });
  } else if (up && last - S1 <= 1.2 * a) {
    p = plan({ kind: "Pullback", bias: "Bullish", name: "Buy the pullback to support", minRisk: 0.5 * a,
      entry: Math.max(S1, last - 0.25 * a), stop: S1 - a, tp1: R1, tp2: R2,
      why: `Uptrend (price above its 50-day average, which is rising) and price is close to support at ${fx(S1)}. Buying near support keeps the stop tight.` });
  } else if (up) {
    const zone = Math.max(S1, toTick(s20));
    p = plan({ kind: "Wait", bias: "Bullish", name: "Uptrend, but stretched: wait for a pullback", minRisk: 0.5 * a,
      entry: zone, stop: Math.min(S1, zone) - a, tp1: Math.max(R1, last), tp2: R2,
      why: `The trend is up, but price is ${((last - zone) / a).toFixed(1)} ATRs above the nearest buy zone. Chasing here gives a poor risk/reward; a limit order near ${fx(zone)} is the patient plan.` });
  } else if (down) {
    p = plan({ kind: "Reversal", bias: "Bearish", name: "Downtrend: no buy until it reclaims resistance", minRisk: 0.5 * a,
      entry: R1 + tickSize(R1), stop: R1 - a, tp1: R2, tp2: null,
      why: `Price is below a falling 50-day average. Buying now is catching a falling knife. Only consider it if price closes above resistance at ${fx(R1)}; that's the trigger shown.` });
  } else {
    p = plan({ kind: "Range", bias: "Neutral", name: "Range trade: buy support, sell resistance", minRisk: 0.5 * a,
      entry: Math.max(S1, last - 0.25 * a), stop: S1 - 0.75 * a, tp1: R1 - tickSize(R1), tp2: R2,
      why: `No clear trend; price is moving between support ${fx(S1)} and resistance ${fx(R1)}. Buy near the bottom of the range, take profit near the top, and exit if support breaks.` });
  }
  // No support below price: the stock is at fresh lows, so the stop has nothing to hide under
  if (!sup.length) p.warning = "No support below the current price: the stock is at or near its lowest level in a year, so there's no floor to lean on.";
  return { trend, atr: a, levels: lv, supports: sup.slice(0, 3), resistances: res.slice(0, 3), volRatio, sma20: s20, sma50: s50, sma200: s200, plan: p };
}

// Day trades: in and out the same session, using 15-minute bars
function daySetup(bars, volumes) {
  const dayOf = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  const days = [...new Set(bars.map((b) => dayOf(b[0])))];
  if (days.length < 2) return null;
  const today = days[days.length - 1], prevDay = days[days.length - 2];
  const tb = bars.filter((b) => dayOf(b[0]) === today), tv = volumes.filter((_, i) => dayOf(bars[i][0]) === today);
  const pb = bars.filter((b) => dayOf(b[0]) === prevDay);
  const H = Math.max(...pb.map((b) => b[2])), L = Math.min(...pb.map((b) => b[3])), C = pb[pb.length - 1][4];

  // Classic floor-trader pivots from the previous session
  const P = (H + L + C) / 3;
  const piv = { P, R1: 2 * P - L, S1: 2 * P - H, R2: P + (H - L), S2: P - (H - L) };

  // VWAP: average price weighted by volume, today so far
  let pv = 0, vv = 0;
  tb.forEach((b, i) => { const typ = (b[2] + b[3] + b[4]) / 3; pv += typ * tv[i]; vv += tv[i]; });
  const vwap = vv ? pv / vv : null;
  const orh = Math.max(...tb.slice(0, 2).map((b) => b[2])), orl = Math.min(...tb.slice(0, 2).map((b) => b[3])); // first 30 min
  const last = tb[tb.length - 1][4];
  const a = atr(bars.slice(-60));
  const fx = (v) => fmt(v, v < 1 ? 3 : 2);
  const above = vwap != null && last > vwap && last > P;
  const below = vwap != null && last < vwap && last < P;

  let p;
  if (above) {
    const trigger = Math.max(orh, last);
    const targets = [piv.R1, piv.R2, H].filter((x) => x > trigger + tickSize(trigger)).sort((x, y) => x - y);
    p = plan({ kind: "Long", bias: "Bullish", name: "Intraday long above VWAP", minRisk: 0.5 * a,
      entry: trigger, stop: Math.max(vwap, orl) - tickSize(vwap), tp1: targets[0], tp2: targets[1],
      why: `Price is above today's VWAP (${fx(vwap)}) and the pivot (${fx(P)}), so buyers are in control. Enter on a break of ${fx(trigger)}, exit if it falls back under VWAP.` });
  } else if (below) {
    p = plan({ kind: "Wait", bias: "Bearish", name: "Sellers in control: wait for a VWAP reclaim", minRisk: 0.5 * a,
      entry: Math.max(vwap, P), stop: Math.min(orl, piv.S1), tp1: piv.R1, tp2: piv.R2,
      why: `Price is below VWAP (${fx(vwap)}) and the pivot (${fx(P)}). No long trade unless it climbs back above ${fx(Math.max(vwap, P))}; the plan shown is that trigger.` });
  } else {
    p = plan({ kind: "Range", bias: "Neutral", name: "Choppy: trade only the opening range break", minRisk: 0.5 * a,
      entry: orh + tickSize(orh), stop: orl, tp1: piv.R1 > orh ? piv.R1 : null, tp2: piv.R2,
      why: `Price is between VWAP and the pivot: no clear side. Only act if it breaks the first-30-minute high of ${fx(orh)}.` });
  }
  return { session: today, prev: { H, L, C }, pivots: piv, vwap, orh, orl, last, atr: a, plan: p, bars: tb.length };
}

// Shares to buy so that hitting the stop loses about `risk` ringgit (Bursa trades in lots of 100)
function positionSize(riskRM, entry, stop) {
  const perShare = entry - stop;
  if (!(perShare > 0) || !(riskRM > 0)) return null;
  const lots = Math.floor(riskRM / perShare / 100);
  return { lots, shares: lots * 100, cost: lots * 100 * entry, loss: lots * 100 * perShare };
}

// ---- Backtests ----
// Replays history one bar at a time: at each point, build the setup from data available
// then (no peeking ahead), place the order, and see what happened next.

// Play one plan forward from bar `from`. Entry below the price is a limit buy (fills if the
// low reaches it); above is a stop buy (fills if the high reaches it). Once in, whichever of
// stop / TP1 is touched first decides the trade; if both in the same bar we assume the stop
// (the cautious reading). Results are in R (multiples of the amount risked) after costs.
// Returns null if never filled, or { r, outcome, bars, exit }.
const ROUND_TRIP_COST = 0.0025; // ~0.25%: brokerage both ways, clearing fee, stamp duty

function simulate(bars, from, p, { fillWithin, maxHold, lastBar = bars.length - 1 }) {
  const risk = p.entry - p.stop, prevClose = bars[from - 1][4];
  const cost = (p.entry * ROUND_TRIP_COST) / risk;
  const isLimit = p.entry <= prevClose;
  let filled = -1;
  for (let i = from; i <= Math.min(lastBar, from + fillWithin - 1); i++) {
    if (isLimit ? bars[i][3] <= p.entry : bars[i][2] >= p.entry) { filled = i; break; }
  }
  if (filled < 0) return null;
  const end = Math.min(lastBar, filled + maxHold);
  for (let i = filled; i <= end; i++) {
    const hitStop = bars[i][3] <= p.stop, hitTp = bars[i][2] >= p.tp1;
    // A target touched on the fill bar itself is ignored: we can't tell if it came before the fill
    if (hitStop) return { outcome: "loss", r: -1 - cost, bars: i - filled, exit: i };
    if (hitTp && i > filled) return { outcome: "win", r: (p.tp1 - p.entry) / risk - cost, bars: i - filled, exit: i };
  }
  return { outcome: "timeout", r: (bars[end][4] - p.entry) / risk - cost, bars: end - filled, exit: end };
}

function summarise(trades) {
  const by = {};
  for (const t of trades) (by[t.kind] ||= []).push(t);
  const stats = (ts) => {
    const n = ts.length, w = ts.filter((t) => t.outcome === "win").length, l = ts.filter((t) => t.outcome === "loss").length;
    return { trades: n, wins: w, losses: l, timeouts: n - w - l, winRate: n ? w / n : null,
      avgR: n ? ts.reduce((a, t) => a + t.r, 0) / n : null, avgBars: n ? ts.reduce((a, t) => a + t.bars, 0) / n : null };
  };
  return { all: stats(trades), good: stats(trades.filter((t) => t.good)),
    byKind: Object.fromEntries(Object.entries(by).map(([k, ts]) => [k, stats(ts)])), trades };
}

// Swing: re-run the daily setup every day of the last ~2 years; one position at a time.
// Orders stay open 5 days; trades are closed after 30 days if neither level is hit.
function backtestSwing(candles, volumes) {
  const trades = [];
  for (let i = 200; i < candles.length - 1; i++) {
    let sw;
    try { sw = swingSetup(candles.slice(0, i + 1), volumes.slice(0, i + 1)); } catch { continue; }
    const p = sw.plan;
    const res = simulate(candles, i + 1, p, { fillWithin: 5, maxHold: 30 });
    if (!res) continue;
    trades.push({ kind: p.kind, good: p.good, date: candles[i + 1][0], entry: p.entry, ...res });
    i = res.exit; // wait for this trade to finish before taking the next
  }
  return summarise(trades);
}

// Day trades: for each session, build the setup after the first 30 minutes, then trade
// the rest of that session only; anything still open is closed at the session's last bar.
function backtestDay(bars, volumes) {
  const dayOf = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  const starts = [];
  bars.forEach((b, i) => { if (!i || dayOf(b[0]) !== dayOf(bars[i - 1][0])) starts.push(i); });
  const trades = [];
  for (let d = 1; d < starts.length; d++) {
    const s = starts[d], end = (starts[d + 1] ?? bars.length) - 1;
    if (end - s < 4) continue;
    let ds;
    try { ds = daySetup(bars.slice(0, s + 2), volumes.slice(0, s + 2)); } catch { continue; }
    if (!ds) continue;
    const p = ds.plan;
    const res = simulate(bars, s + 2, p, { fillWithin: end - s - 2, maxHold: Infinity, lastBar: end });
    if (!res) continue;
    trades.push({ kind: p.kind, good: p.good, date: dayOf(bars[s][0]), entry: p.entry, ...res });
  }
  return summarise(trades);
}
