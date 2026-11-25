"""Price changes for market indicators and per-stock drivers (oil, ringgit, peers...)."""
import warnings

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

_cache = {}


def daily(ticker: str, period: str):
    """Daily prices. Yahoo sometimes drops an index's whole session from its daily data, which turns
    "since yesterday" into "since two days ago", so missing days are rebuilt from 5-minute prices."""
    h = yf.Ticker(ticker).history(period=period).dropna(subset=["Close"])
    if not (ticker.startswith("^") or ticker.endswith(".SS")):
        return h  # currencies and futures trade round the clock, so their days can't be rebuilt this way
    try:
        m = yf.Ticker(ticker).history(period="5d", interval="5m").dropna(subset=["Close"])
        have, rows = set(h.index.date), {}
        for day, g in m.groupby(m.index.date):
            if day not in have:
                rows[pd.Timestamp(day, tz=h.index.tz)] = {"Open": g["Open"].iloc[0], "High": g["High"].max(),
                                                          "Low": g["Low"].min(), "Close": g["Close"].iloc[-1]}
        if rows:
            print(f"     {ticker}: rebuilt missing {', '.join(str(d.date()) for d in rows)}")
            h = pd.concat([h, pd.DataFrame.from_dict(rows, orient="index")]).sort_index()
    except Exception as e:
        print(f"     {ticker}: couldn't check for missing days: {e}")
    return h


def snapshot(ticker: str) -> dict:
    if ticker in _cache:
        return _cache[ticker]
    snap = {"ticker": ticker, "last": None, "d1": None, "m1": None, "m3": None}
    try:
        close = daily(ticker, "6mo")["Close"]
        last = float(close.iloc[-1])
        snap.update(
            last=last,
            d1=_chg(last, close, 2),
            m1=_chg(last, close, 22),
            m3=_chg(last, close, 64),
        )
    except Exception as e:
        print(f"     macro fetch failed for {ticker}: {e}")
    _cache[ticker] = snap
    return snap


def _chg(last, close, n):
    return float((last / close.iloc[-n] - 1) * 100) if len(close) >= n else None


def drivers_for(stock: dict) -> list:
    out = []
    for d in stock.get("drivers", []):
        snap = snapshot(d["ticker"])
        impact = None
        if snap["m1"] is not None:
            # A driver moving up is good for the stock if its effect is positive, and vice versa.
            # Monthly moves under 1% are treated as noise.
            sign = 1 if d["effect"] == "positive" else -1
            if abs(snap["m1"]) < 1:
                impact = "Neutral"
            else:
                impact = "Tailwind" if snap["m1"] * sign > 0 else "Headwind"
        out.append({**d, **snap, "impact": impact})
    return out
