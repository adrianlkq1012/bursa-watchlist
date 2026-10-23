// Browser version of agent/indicators.py and agent/signals.py, so stocks fetched on demand
// get the same indicators and rule-based signals as the watchlist. Keep the two in step.

function sma(xs, n) {
  const out = new Array(xs.length).fill(null);
  let sum = 0;
  xs.forEach((x, i) => { sum += x; if (i >= n) sum -= xs[i - n]; if (i >= n - 1) out[i] = sum / n; });
  return out;
}

// pandas ewm(adjust=False): seeded with the first value
function ema(xs, alpha) {
  const out = [];
  xs.forEach((x, i) => out.push(i === 0 ? x : alpha * x + (1 - alpha) * out[i - 1]));
  return out;
}

function analyse(candles, volumes, ratios) {
  const close = candles.map((c) => c[4]);
  const n = close.length;
  const s50 = sma(close, 50), s200 = sma(close, 200), v20 = sma(volumes, 20);

  // RSI with Wilder's smoothing (alpha 1/14), as in indicators.py
  const delta = close.map((c, i) => (i ? c - close[i - 1] : 0));
  const gain = ema(delta.map((d) => Math.max(d, 0)), 1 / 14), loss = ema(delta.map((d) => Math.max(-d, 0)), 1 / 14);
  const rsi = n >= 15 ? 100 - 100 / (1 + gain[n - 1] / loss[n - 1]) : null;

  const ema26 = ema(close, 2 / 27);
  const macd = ema(close, 2 / 13).map((v, i) => v - ema26[i]);
  const hist = macd[n - 1] - ema(macd, 2 / 10)[n - 1];

  const last = close[n - 1], L50 = s50[n - 1], L200 = s200[n - 1];
  const tail = (k) => candles.slice(-k);
  const levels = {
    high_52w: Math.max(...tail(252).map((c) => c[2])), low_52w: Math.min(...tail(252).map((c) => c[3])),
    resistance_3m: Math.max(...tail(63).map((c) => c[2])), support_3m: Math.min(...tail(63).map((c) => c[3])),
    sma50: L50, sma200: L200,
  };

  let trend = null;
  if (n >= 60) {
    let score = 0;
    const reasons = [];
    if (L200 != null) {
      if (last > L200) { score += 1; reasons.push(["+", `Price is above its 200-day average (${L200.toFixed(3)}): long-term uptrend.`]); }
      else { score -= 1; reasons.push(["-", `Price is below its 200-day average (${L200.toFixed(3)}): long-term downtrend.`]); }
      const prev = s200[n - 21];
      if (prev != null) {
        if (L200 > prev) { score += 1; reasons.push(["+", "The 200-day average is rising over the last month."]); }
        else { score -= 1; reasons.push(["-", "The 200-day average is falling over the last month."]); }
      }
    }
    if (L50 != null && L200 != null) {
      if (L50 > L200) { score += 1; reasons.push(["+", "50-day average is above the 200-day (golden-cross structure)."]); }
      else { score -= 1; reasons.push(["-", "50-day average is below the 200-day (death-cross structure)."]); }
    }
    if (rsi != null) {
      if (rsi > 70) { score -= 0.5; reasons.push(["-", `RSI ${rsi.toFixed(0)} is overbought: avoid chasing, wait for a pullback.`]); }
      else if (rsi < 30) { score += 0.5; reasons.push(["+", `RSI ${rsi.toFixed(0)} is oversold: possible bounce zone if fundamentals hold.`]); }
      else reasons.push(["=", `RSI ${rsi.toFixed(0)} is neutral.`]);
    }
    if (hist > 0) { score += 0.5; reasons.push(["+", "MACD is above its signal line: short-term momentum is positive."]); }
    else { score -= 0.5; reasons.push(["-", "MACD is below its signal line: short-term momentum is negative."]); }
    trend = { score, reasons, label: label(score, 2) };
  }

  const valuation = valuationSignals(ratios);
  const total = (trend?.score || 0) + valuation.score;
  return {
    trend, valuation, levels,
    rating: !trend ? "Neutral" : total >= 3 ? "Bullish" : total <= -3 ? "Bearish" : "Neutral",
    indicators: { rsi, macd_hist: hist, vol_ratio: v20[n - 1] ? volumes[n - 1] / v20[n - 1] : null },
    sma50: candles.map((c, i) => [c[0], s50[i]]).filter((p) => p[1] != null),
    sma200: candles.map((c, i) => [c[0], s200[i]]).filter((p) => p[1] != null),
  };
}

function valuationSignals(f) {
  let score = 0;
  const reasons = [];
  const { pe, pb, dividend_yield: dy, debt_to_equity: de } = f;
  if (pe == null) { score -= 1; reasons.push(["-", "No trailing P/E: the company is loss-making over the last 12 months."]); }
  else if (pe < 12) { score += 1; reasons.push(["+", `P/E ${pe.toFixed(1)} is low (cheap relative to earnings).`]); }
  else if (pe > 25) { score -= 1; reasons.push(["-", `P/E ${pe.toFixed(1)} is high (market is pricing in a lot of growth).`]); }
  else reasons.push(["=", `P/E ${pe.toFixed(1)} is moderate.`]);
  if (pb != null) {
    if (pb < 1) { score += 0.5; reasons.push(["+", `P/B ${pb.toFixed(2)} is below 1: trading under book value.`]); }
    else if (pb > 3) { score -= 0.5; reasons.push(["-", `P/B ${pb.toFixed(2)} is rich versus book value.`]); }
    else reasons.push(["=", `P/B ${pb.toFixed(2)}.`]);
  }
  if (dy > 0) {
    if (dy >= 4) { score += 1; reasons.push(["+", `Dividend yield ${dy.toFixed(2)}% is attractive.`]); }
    else reasons.push(["=", `Dividend yield ${dy.toFixed(2)}%.`]);
  } else reasons.push(["=", "No dividend currently."]);
  if (de != null && de > 150) { score -= 0.5; reasons.push(["-", `Debt-to-equity ${de.toFixed(0)}% is high.`]); }
  return { score, reasons, label: label(score, 1) };
}

function label(score, t) {
  return score >= t ? "Positive" : score <= -t ? "Negative" : "Mixed";
}
