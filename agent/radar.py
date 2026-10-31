"""Global Market Radar: the day's big market stories (earnings, war, policy, commodities),
the moves they caused, and what they mean for Bursa. Shown at the top of the home page, rebuilt every run."""
import json
import urllib.request
from datetime import datetime

import yfinance as yf

from agent import ai, news

# (ticker, label, unit) - unit "pt" means the change is shown in points, not percent
MARKETS = [
    ("^IXIC", "Nasdaq", "%"), ("^GSPC", "S&P 500", "%"), ("^DJI", "Dow Jones", "%"),
    ("^SOX", "Philadelphia Semiconductor index", "%"),
    ("^N225", "Nikkei 225", "%"), ("^HSI", "Hang Seng", "%"), ("000001.SS", "Shanghai Composite", "%"),
    ("^STI", "Singapore STI", "%"),
    ("BZ=F", "Brent crude (US$/barrel)", "%"), ("GC=F", "Gold (US$/oz)", "%"),
    ("^TNX", "US 10-year Treasury yield (%)", "pt"), ("DX-Y.NYB", "US dollar index", "%"),
    ("MYR=X", "USD/MYR", "%"), ("^KLSE", "FBM KLCI", "%"),
]

# Topics for the news search: the stories that move markets, not just market wraps
NEWS_QUERIES = [
    "Wall Street stocks", "stock market today", "shares earnings results", "semiconductor stocks",
    "AI stocks", "CPI inflation report", "jobs report nonfarm payrolls", "FOMC Fed rate decision",
    "Fed Powell", "war markets", "geopolitical tensions oil",
    "ceasefire talks", "tariffs trade", "China economy", "oil prices", "gold prices", "crude palm oil",
    "Asian markets", "Bursa Malaysia", "ringgit", "Bank Negara OPR", "Malaysia economy",
]

# Megacaps and chipmakers whose moves spill over to Bursa tech, tracked even on quiet days
US_KEY = {
    "NVDA": "Nvidia", "AMD": "AMD", "INTC": "Intel", "AVGO": "Broadcom", "TSM": "TSMC", "MU": "Micron",
    "QCOM": "Qualcomm", "ASML": "ASML", "AMAT": "Applied Materials", "AAPL": "Apple", "MSFT": "Microsoft",
    "GOOGL": "Alphabet", "AMZN": "Amazon", "META": "Meta", "TSLA": "Tesla", "ORCL": "Oracle",
}

# Bursa groups that usually react to world news, by stock code
BURSA_SECTORS = {
    "Tech & semiconductors": ["0166", "3867", "5005", "0128", "0208", "0097", "6963"],
    "Oil & gas": ["7277", "7293", "5210", "5199", "5183"],
    "Banks": ["1155", "1295", "1023", "1066", "5819"],
    "Plantation": ["5285", "2445", "1961"],
    "Utilities & data centres": ["5347", "4677", "6742"],
    "Construction": ["5398", "5263", "3336", "5211"],
    "Gloves": ["7113", "5168"],
    "Consumer & gaming": ["3182", "4715", "5296", "5326", "7084"],
}


def quote(ticker: str, label: str, unit: str) -> dict:
    q = {"ticker": ticker, "label": label}
    try:
        close = yf.Ticker(ticker).history(period="1mo")["Close"].dropna()
        last, prev = float(close.iloc[-1]), float(close.iloc[-2])
        q.update(
            last=round(last, 4), prev=round(prev, 4),
            session=close.index[-1].strftime("%A %Y-%m-%d"),
            change=round(last - prev, 4),
            change_pct=round((last / prev - 1) * 100, 2) if unit == "%" else None,
            week_pct=round((last / float(close.iloc[-6]) - 1) * 100, 2) if len(close) >= 6 and unit == "%" else None,
        )
    except Exception as e:
        print(f"     radar fetch failed for {ticker}: {e}")
    return q


def us_movers() -> dict:
    """The latest US session's biggest moves among large companies, plus the key tech names'
    moves over the last few sessions (an earnings crash two days ago still matters today)."""
    big = {}
    for screen in ("day_losers", "day_gainers", "most_actives"):
        try:
            for x in yf.screen(screen, count=100)["quotes"]:
                if (x.get("marketCap") or 0) >= 20e9 and x.get("regularMarketChangePercent") is not None:
                    big[x["symbol"]] = {"name": x.get("shortName") or x["symbol"], "ticker": x["symbol"],
                                        "change_pct": round(x["regularMarketChangePercent"], 2),
                                        "market_cap_usd_bn": round(x["marketCap"] / 1e9)}
        except Exception as e:
            print(f"     radar US screen {screen} failed: {e}")
    movers = sorted(big.values(), key=lambda m: -abs(m["change_pct"]))[:20]

    key = []
    try:
        closes = yf.download(list(US_KEY), period="1mo", progress=False)["Close"]
        for t, name in US_KEY.items():
            c = closes[t].dropna()
            pct = lambda a, b: round((float(c.iloc[a]) / float(c.iloc[b]) - 1) * 100, 2)
            key.append({"name": name, "ticker": t, "last": round(float(c.iloc[-1]), 2),
                        "last_session_pct": pct(-1, -2), "previous_session_pct": pct(-2, -3), "five_day_pct": pct(-1, -6)})
    except Exception as e:
        print(f"     radar US key stocks failed: {e}")
    return {"big_movers_last_session": movers, "key_stocks": key}


def bursa(relay: str) -> dict:
    """Breadth, big-cap movers and sector moves for Bursa's latest session, from the relay's screener."""
    try:
        req = urllib.request.Request(relay + "/screen", headers={"User-Agent": "Mozilla/5.0 (bursa-watchlist build)"})
        rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        print(f"     radar Bursa screen failed: {e}")
        return {}
    ch = [r["ch"] for r in rows if r.get("ch") is not None]
    big = sorted((r for r in rows if r.get("ch") is not None and (r.get("mc") or 0) >= 5e9), key=lambda r: r["ch"])
    pick = lambda xs: [f"{r['s']} {r['ch']:+.2f}%" for r in xs]
    by_code = {r["c"]: r for r in rows if r.get("ch") is not None}
    sectors = {}
    for sector, codes in BURSA_SECTORS.items():
        members = [by_code[c] for c in codes if c in by_code]
        if members:
            sectors[sector] = {"average_pct": round(sum(r["ch"] for r in members) / len(members), 2),
                               "stocks": pick(members)}
    return {
        "gainers": sum(c > 0 for c in ch), "losers": sum(c < 0 for c in ch),
        "large_cap_gainers": pick(big[::-1][:6]), "large_cap_losers": pick(big[:6]),
        "sectors": sectors,
    }


def build(relay: str, now: datetime) -> dict:
    weekend = now.weekday() >= 5
    morning = now.hour < 12 and not weekend
    radar = {
        "date": now.strftime("%-d %B %Y | %A"),
        "time": now.strftime("%H:%M"),
        "edition": "Weekend edition, looking back on the week" if weekend
                   else "Morning edition, before Bursa opens" if morning else "Evening edition, after Bursa closes",
        "markets": [quote(*m) for m in MARKETS],
        "us": us_movers(),
        "bursa": bursa(relay),
        # Mondays and Saturdays look back over the weekend
        "news": news.bing_many(NEWS_QUERIES, days=3 if now.weekday() in (0, 5, 6) else 2, limit=70)
                or news.search_many(NEWS_QUERIES, days=2, limit=40),
    }
    if ai.available():
        radar["ai"] = ai.market_radar(radar, morning)
        print(f"AI   market radar: {'ok' if radar['ai'] else 'failed'}")
    return radar
