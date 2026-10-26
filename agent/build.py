"""Analyse every stock on the owner's watchlist and write the site into docs/.

The watchlist itself lives on the relay (edited from the site with the owner passcode);
watchlist.json adds optional per-stock settings such as news queries and drivers.
"""
import json
import math
import os
import re
import shutil
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf

from agent import ai, news
from agent.data import fetch_fundamentals, fetch_prices, ticker_for
from agent.indicators import add_indicators, key_levels
from agent.macro import drivers_for, snapshot
from agent.signals import overall, trend_signals, valuation_signals

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "agent" / "web"
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
        "drivers": drivers_for(stock),
        "news": news.search(stock.get("news_query", f'"{stock["name"]}"'), days=30, limit=8,
                            match=stock.get("news_match")),
    }


def _f(v):
    try:
        return None if v is None or math.isnan(v) else float(v)
    except TypeError:
        return None


def _line(df, col):
    return [{"time": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in df[col].dropna().items()]


def relay_url() -> str:
    return (os.environ.get("RELAY_URL") or (ROOT / "relay" / "url.txt").read_text().strip()).rstrip("/")


def stock_for(code: str, known: list) -> dict:
    """Settings from watchlist.json if present, otherwise just the name from Yahoo."""
    for s in known:
        if s["code"] == code:
            return s
    info = yf.Ticker(ticker_for(code)).info or {}
    name = info.get("longName") or info.get("shortName")
    if not name:
        raise SystemExit(f"Unknown Bursa code: {code}")
    return {"code": code, "name": name, "short": info.get("shortName") or code}


def watchlist_codes(config: dict) -> list:
    """The owner's list from the relay; falls back to watchlist.json if the relay is down."""
    try:
        # Cloudflare turns away Python's default user agent
        req = urllib.request.Request(relay_url() + "/watchlist", headers={"User-Agent": "Mozilla/5.0 (bursa-watchlist build)"})
        codes = json.loads(urllib.request.urlopen(req, timeout=30).read())["codes"]
        print(f"LIST {len(codes)} stocks from the online watchlist: {', '.join(codes)}")
        return codes
    except Exception as e:
        print(f"LIST relay unavailable ({e}); using watchlist.json")
        return [s["code"] for s in config["stocks"]]


def main():
    config = json.loads((ROOT / "watchlist.json").read_text())
    results = []
    stocks = []
    for code in watchlist_codes(config):
        try:
            stocks.append(stock_for(code, config["stocks"]))
        except (SystemExit, Exception) as e:
            print(f"FAIL {code}: {e}")
    for s in stocks:
        try:
            results.append(analyse(s))
            print(f"OK   {s['short']} ({s['code']})")
        except Exception as e:
            print(f"FAIL {s['short']} ({s['code']}): {e}")
    if stocks and not results:
        # Fail loudly so the cloud run keeps the last good dashboard online
        raise SystemExit("No stocks could be analysed")

    mcfg = config.get("market", {})
    market = {
        "indicators": [{**m, **snapshot(m["ticker"])} for m in mcfg.get("indicators", [])],
        "news": news.search_many(mcfg.get("news_queries", []), days=3, limit=10),
    }

    if ai.available():
        print("AI   writing briefs via Gemini")
        market["brief"] = ai.market_brief(market, results)
        print(f"AI   market: {'ok' if market['brief'] else 'failed'}")
        for s in results:
            s["brief"] = ai.stock_brief(s)
            print(f"AI   {s['short']}: {'ok' if s['brief'] else 'failed'}")
    else:
        print("AI   skipped (no Gemini key; see agent/ai.py)")

    docs = ROOT / "docs"
    (docs / "reports").mkdir(parents=True, exist_ok=True)
    # ?v=<build time> on scripts and styles so browsers fetch fresh copies after each update
    version = datetime.now(MYT).strftime("%Y%m%d%H%M")
    bust = lambda html: re.sub(r'(src|href)="(\w+\.(?:js|css))"', rf'\1="\2?v={version}"', html)
    for name in ("style.css", "common.js", "chat.js", "signals.js", "trading.js", "report.html"):
        shutil.copy(WEB / name, docs / name)
    (docs / "stock.html").write_text(bust((WEB / "stock.html").read_text()))
    (docs / "config.js").write_text((WEB / "config.js").read_text().replace("__RELAY_URL__", relay_url()))
    reports = []
    for path in sorted((ROOT / "reports").glob("*.json")):
        shutil.copy(path, docs / "reports" / path.name)
        r = json.loads(path.read_text())
        reports.append({"code": r["code"], "name": r["name"], "short": r["short"], "generated": r.get("generated"),
                        "stance": (r.get("report") or {}).get("verdict", {}).get("stance")})

    payload = {
        "generated": datetime.now(MYT).strftime("%Y-%m-%d %H:%M MYT"),
        "ai_enabled": ai.available(),
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "market": market,
        "reports": reports,
        # The watchlist page fetches prices live; it only needs what the evening run adds
        "briefs": {s["code"]: {"brief": s.get("brief"), "news": s.get("news"),
                               "drivers": [{k: d.get(k) for k in ("label", "why", "m1", "impact")} for d in s.get("drivers", [])]}
                   for s in results},
    }
    home = {
        "generated": payload["generated"], "repo": payload["repo"], "reports": reports,
        "market": {"indicators": market["indicators"], "brief": market.get("brief")},
        "watchlist": [{"code": s["code"], "short": s["short"], "close": s["close"], "change_pct": s["change_pct"],
                       "stance": (s.get("brief") or {}).get("stance")} for s in results],
    }
    for page, data in (("index.html", home), ("watchlist.html", payload)):
        html = bust((WEB / page).read_text()).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
        (docs / page).write_text(html)
    print(f"Wrote home and watchlist pages with {len(reports)} deep-dive report(s)")


if __name__ == "__main__":
    main()
