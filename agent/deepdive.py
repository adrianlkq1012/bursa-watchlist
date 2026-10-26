"""Full due-diligence report on one or more companies, saved to reports/<code>.json.

    python -m agent.deepdive 5161          # one company (any Bursa code)
    python -m agent.deepdive 5161 7113     # several
    python -m agent.deepdive               # every stock on the owner's watchlist
"""
import json
import re
import sys
from datetime import datetime

from agent import ai, news
from agent.build import MYT, ROOT, analyse, stock_for, watchlist_codes
from agent.data import fetch_financials

REPORTS = ROOT / "reports"


def performance(candles: list) -> dict:
    closes = [c["close"] for c in candles]
    out = {}
    for label, n in (("1m", 21), ("6m", 126), ("1y", 252), ("2y", 500)):
        if len(closes) > n:
            out[label] = round((closes[-1] / closes[-n - 1] - 1) * 100, 1)
    return out


def run(code: str, watchlist: list) -> None:
    stock = stock_for(code, watchlist)
    print(f"DEEP {stock['short']} ({code}): fetching data")
    s = analyse(stock)
    s["financials"] = fetch_financials(code)
    s["news"] = news.search(stock.get("news_query", f'"{s["name"]}"'), days=90, limit=15,
                            match=stock.get("news_match"))
    s["performance"] = performance(s["candles"])

    ai_input = {
        "company": f"{s['name']} ({s['short']}, Bursa code {code})",
        "sector": f"{s.get('sector')} / {s.get('industry')}",
        "business_summary": s.get("summary"),
        "price_rm": round(s["close"], 3),
        "price_performance_pct": s["performance"],
        "key_levels_rm": s["levels"],
        "trend_signals": [r[1] for r in s["trend"]["reasons"]],
        "valuation_signals": [r[1] for r in s["valuation"]["reasons"]],
        "ratios": s["fundamentals"],
        "annual_financials_rm": s["financials"]["annual"],
        "quarterly_financials_rm": s["financials"]["quarterly"],
        "dividends_per_share_by_year_rm": s["financials"]["dividends_by_year"],
        "ownership": s["financials"]["ownership"],
        "officers": s["financials"]["officers"],
        "profile": s["financials"]["profile"],
        "external_drivers": [{k: d.get(k) for k in ("label", "why", "m1", "m3", "impact")} for d in s["drivers"]],
        "news_last_90_days": [f"{n['date']} | {n['source']} | {n['title']}" for n in s["news"]],
    }
    print(f"DEEP {stock['short']}: writing AI report")
    report, sources = ai.deep_dive(ai_input)
    print(f"DEEP {stock['short']}: AI {'ok' if report else 'failed'}, {len(sources)} web sources")

    s.pop("brief", None)
    s.update(report=report, sources=sources, generated=datetime.now(MYT).strftime("%Y-%m-%d %H:%M MYT"))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{code}.json").write_text(json.dumps(s, default=str))
    print(f"DEEP wrote reports/{code}.json")


def main(codes: list) -> None:
    config = json.loads((ROOT / "watchlist.json").read_text())
    watchlist = config["stocks"]
    codes = codes or watchlist_codes(config)
    for code in codes:
        code = code.strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{4,6}", code):
            raise SystemExit(f"Not a Bursa stock code: {code!r}")
        run(code, watchlist)


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]).replace(",", " ").split())
