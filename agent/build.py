"""Run the analysis for every stock in watchlist.json and write docs/index.html."""
import json
import math
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent import ai, news
from agent.data import fetch_fundamentals, fetch_prices
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


def main():
    config = json.loads((ROOT / "watchlist.json").read_text())
    results = []
    for s in config["stocks"]:
        try:
            results.append(analyse(s))
            print(f"OK   {s['short']} ({s['code']})")
        except Exception as e:
            print(f"FAIL {s['short']} ({s['code']}): {e}")
    if not results:
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
    for name in ("style.css", "common.js", "chat.js", "signals.js", "stock.html", "report.html"):
        shutil.copy(WEB / name, docs / name)
    relay_url = os.environ.get("RELAY_URL") or (ROOT / "relay" / "url.txt").read_text().strip()
    (docs / "config.js").write_text((WEB / "config.js").read_text().replace("__RELAY_URL__", relay_url.rstrip("/")))
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
        "stocks": results,
        "reports": reports,
    }
    home = {
        "generated": payload["generated"], "repo": payload["repo"], "reports": reports,
        "market": {"indicators": market["indicators"], "brief": market.get("brief")},
        "watchlist": [{"code": s["code"], "short": s["short"], "close": s["close"], "change_pct": s["change_pct"],
                       "stance": (s.get("brief") or {}).get("stance")} for s in results],
    }
    for page, data in (("index.html", home), ("watchlist.html", payload)):
        html = (WEB / page).read_text().replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
        (docs / page).write_text(html)
    print(f"Wrote home and watchlist pages with {len(reports)} deep-dive report(s)")


if __name__ == "__main__":
    main()
