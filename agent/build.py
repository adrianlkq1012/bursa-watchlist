"""Run the analysis for every stock in watchlist.json and write docs/index.html."""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent.data import fetch_fundamentals, fetch_prices
from agent.indicators import add_indicators, key_levels
from agent.signals import overall, trend_signals, valuation_signals

ROOT = Path(__file__).resolve().parent.parent
MYT = timezone(timedelta(hours=8))


def analyse(stock: dict) -> dict:
    df = add_indicators(fetch_prices(stock["code"]))
    fund = fetch_fundamentals(stock["code"])
    trend = trend_signals(df)
    val = valuation_signals(fund)
    last, prev = df.iloc[-1], df.iloc[-2]

    chart = df.tail(500)
    return {
        **stock,
        "sector": fund.get("sector"),
        "industry": fund.get("industry"),
        "summary": fund.get("summary"),
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
        "close": float(last["Close"]),
        "change_pct": float((last["Close"] / prev["Close"] - 1) * 100),
        "rating": overall(trend, val),
        "trend": trend,
        "valuation": val,
        "levels": {**key_levels(df), "sma50": _f(last["SMA50"]), "sma200": _f(last["SMA200"])},
        "indicators": {
            "rsi": _f(last["RSI14"]),
            "macd_hist": _f(last["MACD_hist"]),
            "vol_ratio": _f(last["Volume"] / last["VOL20"]) if last["VOL20"] else None,
        },
        "fundamentals": {k: fund.get(k) for k in (
            "market_cap", "pe", "forward_pe", "pb", "dividend_yield", "eps",
            "roe", "debt_to_equity", "profit_margin")},
        "annual": fund.get("annual", []),
        "candles": [
            {"time": d.strftime("%Y-%m-%d"), "open": r.Open, "high": r.High, "low": r.Low, "close": r.Close}
            for d, r in chart.iterrows()
        ],
        "sma50": _line(chart, "SMA50"),
        "sma200": _line(chart, "SMA200"),
    }


def _f(v):
    try:
        return None if v is None or math.isnan(v) else float(v)
    except TypeError:
        return None


def _line(df, col):
    return [{"time": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in df[col].dropna().items()]


def main():
    watchlist = json.loads((ROOT / "watchlist.json").read_text())["stocks"]
    results = []
    for s in watchlist:
        try:
            results.append(analyse(s))
            print(f"OK   {s['short']} ({s['code']})")
        except Exception as e:
            print(f"FAIL {s['short']} ({s['code']}): {e}")
    if not results:
        # Fail loudly so the cloud run keeps the last good dashboard online
        raise SystemExit("No stocks could be analysed")

    payload = {"generated": datetime.now(MYT).strftime("%Y-%m-%d %H:%M MYT"), "stocks": results}
    template = (ROOT / "agent" / "template.html").read_text()
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("__DATA__", json.dumps(payload).replace("</", "<\\/")))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
