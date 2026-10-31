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


def _ask(task: str, data: dict, system: str = SYSTEM):
    token = _token()
    if not token:
        return None
    body = {
        "messages": [
            {"role": "system", "content": system},
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



RADAR_SYSTEM = """You are a sharp global markets strategist writing the daily briefing for Malaysian
investors who hold Bursa stocks. They want to know what actually happened in the world and why it
matters to them, told as stories with cause and effect, not a list of indicator readings.
Rules:
- Use ONLY facts in the data (prices, moves, news headlines and summaries). Never invent numbers, quotes or events.
- Lead with the biggest stories: earnings shocks and big company moves, wars and geopolitics, key economic
  releases and central banks, trade and tariffs, commodity shocks. Name the companies and give their exact moves
  (e.g. "Intel plunged 28.6% after its results").
- Show the chain from cause to effect: what happened -> which stocks and sectors moved, by how much ->
  what it did to the indices -> what it means for Bursa (named sectors and stocks, with their latest moves
  from bursa.sectors when available).
- Explain WHY using the reason in the news (a guidance cut, AI spending worries, ceasefire talks...),
  naming the outlet (e.g. "Reuters reports...").
- Key releases matter most: US CPI and PCE inflation, the jobs report (NFP), FOMC decisions and Powell's
  comments, GDP, and Bank Negara's OPR decision. When one is in the news, report the actual figure against
  what was expected and how stocks reacted.
- Do not write about bond yields or the dollar as stories of their own; mention them only as part of a bigger
  story (e.g. "yields jumped after the hot CPI print").
- Leave out anything that barely moved (a 1bp yield change, a flat index) unless the news makes it a story.
  No filler, no generic statements that would be true on any day.
- Plain English, punchy and specific. Short sentences. Round prices and levels to 2 decimals.
- Reply with a single JSON object matching the requested schema, nothing else."""

RADAR_SCHEMA = """{
  "headline": "the day's main story in one punchy line, max 14 words",
  "intro": "2-3 sentences: what dominated markets, the mood, and the key numbers",
  "items": [{
    "tone": "good | watch | bad (for Bursa investors)",
    "category": "one of: Earnings | Tech & AI | War & geopolitics | Economic data | Central banks | Trade & policy | Commodities | Asia | Bursa | Ringgit | Economy",
    "headline": "names who or what, with the number, e.g. 'Intel crashes 28.6% on weak outlook, drags chip stocks'",
    "what_happened": "2-3 sentences of facts: the specific company, asset and index moves",
    "why": "1-2 sentences: the reason behind it, citing the news outlet",
    "chain": "short cause-and-effect chain with arrows, e.g. 'Intel outlook cut -> INTC -28.6% -> chip index -7.2% -> Nasdaq -2.9%'",
    "malaysia_angle": "1-2 sentences: which Bursa sectors and stocks are affected and how, citing their latest moves if available"
  }],
  "movers": [{"name": "company", "move": "e.g. -28.6% (or -12.6% Thu)", "why": "max 8 words"}],
  "watching": [{"label": "upcoming event or level, e.g. 'US CPI', 'FOMC decision' or 'KLCI 1,600 support'", "value": "when or what level, e.g. 'Fri night MYT'"}],
  "bottom_line": [{"text": "3-6 words", "tone": "good | watch | bad"}],
  "summary": "2 sentences: how the setup looks for Bursa and the next big tests",
  "bursa_focus": "1 sentence: the specific thing to watch on Bursa in the next session",
  "sources": ["numbers of the news items (from news_numbered) you relied on, most important first, up to 8"]
}"""


def market_radar(radar: dict, morning: bool):
    data = {
        "now_malaysia": f"{radar['date']}, {radar['time']} MYT",
        "edition": radar["edition"],
        "indices_commodities_fx": [{k: m.get(k) for k in ("label", "session", "last", "change", "change_pct", "week_pct")}
                                   for m in radar["markets"] if m.get("last") is not None],
        "us_stocks": radar.get("us"),
        "bursa": radar.get("bursa"),
        "news_numbered": [f"{i} | {n['date']} | {n['source']} | {n['title']}" + (f" | {n['summary']}" if n.get("summary") else "")
                          for i, n in enumerate(radar["news"], 1)],
    }
    task = f"""Write today's "Global Market Radar: What Matters for Bursa" ({'morning, before Bursa opens: lead with the overnight stories from the US and Europe' if morning else 'evening, after Bursa closes: lead with what drove Bursa and Asia today, then the overnight setup'}).
Give 4-6 items ranked by importance. Cover a war or geopolitical development if the news has one, and finish with an item on Bursa itself (breadth, sectors, big caps and why they moved).
Use us_stocks: big_movers_last_session for the day's biggest company moves, and key_stocks (with previous_session_pct and five_day_pct) for moves earlier in the week that still matter.
Refer to each session by its weekday (e.g. "Thursday's close"). A market whose session is today and still open (Bursa trades until 17:00 MYT) has not closed: say "so far today".
Only mention a scheduled event (results, CPI, NFP, FOMC, OPR, election, talks) if it appears in the news; put the upcoming ones in "watching".
"movers": 4-8 notable stock moves. "watching": 4-6 entries. "bottom_line": 3-5 entries. Schema:
{RADAR_SCHEMA}"""
    out = _ask(task, data, system=RADAR_SYSTEM)
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
