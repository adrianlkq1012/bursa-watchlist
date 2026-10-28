"""Global Market Radar: overnight world markets, oil, yields and Bursa's last session,
and what each means for Bursa. Shown at the top of the home page, rebuilt every run."""
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

NEWS_QUERIES = [
    "Wall Street stocks close", "oil prices Brent", "Federal Reserve", "Treasury yields",
    "Asian markets stocks", "Bursa Malaysia KLCI", "ringgit", "Malaysia economy",
]


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


def breadth(relay: str) -> dict:
    """Gainers, losers and big-cap movers for Bursa's latest session, from the relay's screener."""
    try:
        req = urllib.request.Request(relay + "/screen", headers={"User-Agent": "Mozilla/5.0 (bursa-watchlist build)"})
        rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        print(f"     radar breadth failed: {e}")
        return {}
    ch = [r["ch"] for r in rows if r.get("ch") is not None]
    big = sorted((r for r in rows if r.get("ch") is not None and (r.get("mc") or 0) >= 5e9), key=lambda r: r["ch"])
    pick = lambda xs: [f"{r['s']} {r['ch']:+.2f}%" for r in xs]
    return {
        "gainers": sum(c > 0 for c in ch), "losers": sum(c < 0 for c in ch),
        "large_cap_gainers": pick(big[::-1][:5]), "large_cap_losers": pick(big[:5]),
    }


def build(relay: str, now: datetime) -> dict:
    morning = now.hour < 12
    radar = {
        "date": now.strftime("%-d %B %Y | %A"),
        "time": now.strftime("%H:%M"),
        "edition": "Morning edition, before Bursa opens" if morning else "Evening edition, after Bursa closes",
        "markets": [quote(*m) for m in MARKETS],
        "bursa": breadth(relay),
        "news": news.search_many(NEWS_QUERIES, days=2, limit=25),
    }
    if ai.available():
        radar["ai"] = ai.market_radar(radar, morning)
        print(f"AI   market radar: {'ok' if radar['ai'] else 'failed'}")
    return radar
