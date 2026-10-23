"""Price changes for market indicators and per-stock drivers (oil, ringgit, peers...)."""
import warnings

import yfinance as yf

warnings.filterwarnings("ignore")

_cache = {}


def snapshot(ticker: str) -> dict:
    if ticker in _cache:
        return _cache[ticker]
    snap = {"ticker": ticker, "last": None, "d1": None, "m1": None, "m3": None}
    try:
        close = yf.Ticker(ticker).history(period="6mo")["Close"].dropna()
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
