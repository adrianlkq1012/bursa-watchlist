"""AI-written briefs via Google's Gemini API (free tier, key from aistudio.google.com).

In GitHub Actions the key comes from the GEMINI_API_KEY repository secret. Locally,
put the key in a file named .gemini-key in the project folder (it is git-ignored),
or set GEMINI_API_KEY.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# Gemini's OpenAI-compatible endpoint
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# "-latest" aliases always point at Google's current models, so they don't get retired
MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
RETRY_WAITS = [0, 20, 60]  # seconds; free-tier models are often briefly overloaded (503)
TIME_BUDGET = 12 * 60  # stop trying after this many seconds in total, so a bad day can't stall the run
_started = time.monotonic()
TOKEN_FILE = Path(__file__).resolve().parent.parent / ".gemini-key"

SYSTEM = """You are an equity research analyst covering Bursa Malaysia, writing for a
mid-to-long-term investor (6-24 month horizon) who wants clear, precise, plain-English analysis.
Rules:
- Use ONLY the data provided. Never invent numbers, events, or analyst targets.
- When you mention a news item, name its source (e.g. "The Edge reports...").
- If the data is thin or conflicting, say so plainly instead of guessing.
- Be specific: refer to actual price levels, ratios and driver moves from the data.
- Reply with a single JSON object matching the requested schema, nothing else."""

STOCK_SCHEMA = """{
  "headline": "one sentence: the single most important thing about this stock right now",
  "what_changed": ["up to 4 short bullets on recent developments from the news, newest first"],
  "drivers": "1-2 sentences on how the listed external drivers are affecting it",
  "stance": "one of: Accumulate | Hold | Wait | Avoid",
  "stance_reason": "2-3 sentences justifying the stance for a 6-24 month investor",
  "entry_plan": "1-2 sentences: price zones (from the key levels) where a patient investor might consider buying, and the level that would invalidate the thesis",
  "risks": ["2-4 key risks"],
  "watch_next": ["2-3 upcoming things to watch, e.g. results, contracts, macro"]
}"""

MARKET_SCHEMA = """{
  "headline": "one sentence summary of today's market backdrop for this investor",
  "points": ["3-5 bullets: the global/local developments that matter most, with numbers"],
  "portfolio": [{"short": "stock short name", "note": "one sentence on how today's backdrop affects it"}]
}"""


def _token():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def available() -> bool:
    return _token() is not None


def _ask(task: str, data: dict):
    token = _token()
    if not token:
        return None
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{task}\n\nDATA:\n{json.dumps(data, default=str)}"},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    for model, wait in ((m, w) for m in MODELS for w in RETRY_WAITS):
        if time.monotonic() - _started + wait > TIME_BUDGET:
            print("     AI time budget used up; skipping")
            return None
        time.sleep(wait)
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({**body, "model": model}).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        raw = b""
        try:
            raw = urllib.request.urlopen(req, timeout=90).read()
            content = json.loads(raw)["choices"][0]["message"]["content"].strip()
            # Some models wrap JSON in ```json fences despite response_format
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            out = json.loads(content)
            out["model"] = model
            return out
        except urllib.error.HTTPError as e:
            print(f"     {model} failed: HTTP {e.code} {e.read()[:200]!r}")
        except Exception as e:
            print(f"     {model} failed: {e} | response: {raw[:300]!r}")
    return None


NATIVE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _ask_grounded(system: str, task: str, data: dict):
    """Gemini with Google Search grounding, for facts not in our data (segments,
    customers, management, recent events). Falls back to no search if grounding
    is unavailable. Returns (parsed JSON, list of source links)."""
    token = _token()
    if not token:
        return None, []
    base = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": f"{task}\n\nDATA:\n{json.dumps(data, default=str)}"}]}],
        "generationConfig": {"temperature": 0.3},
    }
    # One try with Google Search (the free tier often has no search quota: HTTP 429),
    # then the normal retries without it
    attempts = [(MODELS[0], 0, True)] + [(m, w, False) for m in MODELS for w in RETRY_WAITS]
    for model, wait, search in attempts:
        if time.monotonic() - _started + wait > TIME_BUDGET:
            print("     AI time budget used up; skipping")
            break
        time.sleep(wait)
        body = {**base, "tools": [{"google_search": {}}]} if search else base
        req = urllib.request.Request(
            NATIVE.format(model=model),
            data=json.dumps(body).encode(),
            headers={"x-goog-api-key": token, "Content-Type": "application/json"},
        )
        raw = b""
        try:
            raw = urllib.request.urlopen(req, timeout=240).read()
            cand = json.loads(raw)["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
            # Grounded replies can't be forced into JSON mode, so cut out the JSON object
            out = json.loads(text[text.index("{"): text.rindex("}") + 1])
            out["model"] = model + (" + Google Search" if search else "")
            sources = [
                {"title": c["web"].get("title"), "uri": c["web"].get("uri")}
                for c in cand.get("groundingMetadata", {}).get("groundingChunks", []) if "web" in c
            ]
            return out, sources
        except urllib.error.HTTPError as e:
            print(f"     {model} (search={search}) failed: HTTP {e.code} {e.read()[:200]!r}")
        except Exception as e:
            print(f"     {model} (search={search}) failed: {e} | response: {raw[:300]!r}")
    return None, []


DEEP_SYSTEM = SYSTEM.replace(
    "- Use ONLY the data provided. Never invent numbers, events, or analyst targets.",
    "- Numbers (prices, financials, ratios) must come from the DATA provided. Never invent them.\n"
    "- You MAY use Google Search for qualitative facts not in the data: business segments, major\n"
    "  customers, competitors, management background, corporate exercises, recent events. Name the\n"
    "  source for anything found this way.\n"
    "- Fair-value scenarios are your estimates: show the simple maths (e.g. EPS x P/E) behind them.",
)

DEEP_SCHEMA = """{
  "summary": "4-5 sentence executive summary a busy investor can read in 30 seconds",
  "business": {
    "what_they_do": "2-3 sentences in plain English",
    "segments": ["main business segments / products, with share of revenue if known"],
    "customers_and_markets": "who buys from them and where",
    "competitive_position": "competitors and how this company compares",
    "moat": "durable advantages, or say plainly if there is none"
  },
  "management_and_ownership": "2-3 sentences on key people and shareholding (insider %, institutions)",
  "financial_health": {
    "growth": "revenue and profit trend with numbers",
    "profitability": "margins and ROE trend",
    "balance_sheet": "cash, debt, net cash/debt position",
    "cash_flow": "operating cash flow, capex, free cash flow",
    "dividends": "dividend record and sustainability"
  },
  "recent_developments": ["up to 5 recent events, newest first, with source"],
  "valuation": {
    "current": "how the stock is valued now and versus its own history",
    "scenarios": [
      {"case": "Bear", "fair_value_rm": "e.g. 0.30-0.35", "assumptions": "the maths behind it"},
      {"case": "Base", "fair_value_rm": "...", "assumptions": "..."},
      {"case": "Bull", "fair_value_rm": "...", "assumptions": "..."}
    ]
  },
  "bull_case": ["3-4 reasons it could do well"],
  "bear_case": ["3-4 reasons it could do badly"],
  "catalysts": ["upcoming events that could move the price"],
  "risks": ["key risks"],
  "verdict": {
    "stance": "one of: Accumulate | Hold | Wait | Avoid",
    "conviction": "Low | Medium | High",
    "summary": "2-3 sentences for a 6-24 month investor",
    "entry_plan": "price zones to consider buying, from the key levels and fair values",
    "invalidation": "what price or event would make the thesis wrong"
  },
  "verify_yourself": ["3-5 specific things to check in the annual report or Bursa filings before investing"]
}"""


def deep_dive(data: dict):
    return _ask_grounded(DEEP_SYSTEM, f"Write a full due-diligence report on this company. Reply with only this JSON:\n{DEEP_SCHEMA}", data)


def stock_brief(s: dict):
    data = {
        "stock": f"{s['name']} ({s['short']}, Bursa code {s['code']})",
        "sector": f"{s.get('sector')} / {s.get('industry')}",
        "business": (s.get("summary") or "")[:800],
        "price_rm": round(s["close"], 3),
        "day_change_pct": round(s["change_pct"], 2),
        "rule_based_rating": s["rating"],
        "trend_signals": [r[1] for r in s["trend"]["reasons"]],
        "valuation_signals": [r[1] for r in s["valuation"]["reasons"]],
        "key_levels_rm": s["levels"],
        "fundamentals": s["fundamentals"],
        "annual_results_rm": s["annual"],
        "external_drivers": [
            {k: d.get(k) for k in ("label", "why", "last", "d1", "m1", "m3", "impact")} for d in s["drivers"]
        ],
        "news_last_30_days": [f"{n['date']} | {n['source']} | {n['title']}" for n in s["news"]],
    }
    return _ask(f"Write today's brief for this stock. Schema:\n{STOCK_SCHEMA}", data)


def market_brief(market: dict, stocks: list):
    data = {
        "market_indicators": [
            {k: m.get(k) for k in ("label", "last", "d1", "m1", "m3")} for m in market["indicators"]
        ],
        "market_news_last_3_days": [f"{n['date']} | {n['source']} | {n['title']}" for n in market["news"]],
        "portfolio": [
            {"short": s["short"], "name": s["name"], "sector": s.get("industry"), "rating": s["rating"],
             "drivers": [f"{d['label']}: {d.get('impact')}" for d in s["drivers"]]}
            for s in stocks
        ],
    }
    return _ask(f"Write today's market brief for this portfolio. Schema:\n{MARKET_SCHEMA}", data)


RADAR_SCHEMA = """{
  "intro": "2 sentences: the overall mood across world markets and Bursa, with the key reason",
  "items": [{
    "tone": "good | watch | bad (for Bursa investors)",
    "headline": "short headline that leads with the key number, e.g. 'Nasdaq rallies 1.18%: AI confidence returns'",
    "points": ["2-3 short sentences of facts with numbers and the reason behind the move, from the data and news"],
    "malaysia_angle": "1-2 sentences: what this means for Bursa, naming the sectors or kinds of stocks affected"
  }],
  "watching": [{"label": "short name, e.g. 'US 10Y' or 'Fed decision'", "value": "level or timing, e.g. '~4.99%' or 'Thursday morning MYT'"}],
  "bottom_line": [{"text": "3-6 words, e.g. 'Bursa breadth strengthening'", "tone": "good | watch | bad"}],
  "summary": "2 sentences: how constructive the overall setup is and the next big tests",
  "bursa_focus": "1 sentence: the one thing to watch on Bursa in the next session",
  "sources": ["numbers of the news items (from news_numbered) you relied on, most important first, up to 6"]
}"""


def market_radar(radar: dict, morning: bool):
    data = {
        "today_malaysia": f"{radar['date']}, {radar['time']} MYT",
        "edition": radar["edition"],
        "markets_latest_session": [{k: m.get(k) for k in ("label", "session", "last", "prev", "change", "change_pct", "week_pct")}
                                   for m in radar["markets"] if m.get("last") is not None],
        "bursa_latest_session_breadth": radar["bursa"],
        "news_numbered": [f"{i} | {n['date']} | {n['source']} | {n['title']}" for i, n in enumerate(radar["news"], 1)],
    }
    task = f"""Write today's "Global Market Radar: What Matters for Bursa" ({'morning, before Bursa opens: lead with how Wall Street, oil and yields closed overnight' if morning else 'evening, after Bursa closes: lead with how Bursa and Asia closed today'}).
Give 4-5 items covering the biggest drivers: US stocks (and chips/AI), oil, US yields and the Fed, Asia, the ringgit, and the KLCI's latest session with market breadth (gainers vs losers) and the large caps that moved it.
Refer to each market's session by its weekday (e.g. "Tuesday's close"). A market whose session is today and still open (Bursa trades until 17:00 MYT) has not closed: describe it as "so far today". Only mention a scheduled event (Fed meeting, results, data release) if it appears in the news.
"watching" has 4-6 entries; "bottom_line" has 3-5. Schema:
{RADAR_SCHEMA}"""
    out = _ask(task, data)
    if out:
        picked = []
        for n in out.get("sources", []):
            try:
                item = radar["news"][int(n) - 1]
            except (ValueError, IndexError):
                continue
            if item not in picked:
                picked.append(item)
        out["sources"] = [{"title": i["title"], "source": i["source"], "link": i["link"]} for i in picked]
    return out
