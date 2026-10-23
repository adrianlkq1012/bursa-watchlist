"""Recent news headlines from Google News RSS (free, no key)."""
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0"}


def search(query: str, days: int = 30, limit: int = 8, match: list = None) -> list:
    """match: if given, keep only headlines that mention one of these words."""
    q = urllib.parse.quote(f"{query} when:{days}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-MY&gl=MY&ceid=MY:en"
    try:
        xml = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read()
    except Exception as e:
        print(f"     news fetch failed for {query}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items, seen = [], set()
    for it in ET.fromstring(xml).findall(".//item"):
        source = it.findtext("source") or ""
        title = it.findtext("title") or ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        if match and not any(m.lower() in title.lower() for m in match):
            continue
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        try:
            published = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        if published < cutoff:
            continue
        items.append({
            "title": title,
            "source": source,
            "link": it.findtext("link"),
            "date": published.strftime("%Y-%m-%d"),
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit]


def search_many(queries: list, days: int, limit: int) -> list:
    merged, seen = [], set()
    for q in queries:
        for item in search(q, days, limit):
            if item["title"] not in seen:
                seen.add(item["title"])
                merged.append(item)
    merged.sort(key=lambda x: x["date"], reverse=True)
    return merged[:limit]
