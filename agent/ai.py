"""AI-written briefs via GitHub Models (free tier, authenticated with a GitHub token).

In GitHub Actions the built-in GITHUB_TOKEN is used automatically. Locally, put a
fine-grained token with "Models: read" permission in a file named .github-token
in the project folder (it is git-ignored), or set GITHUB_TOKEN.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODELS = ["openai/gpt-4.1", "openai/gpt-4.1-mini"]  # fall back if the first is rate-limited
TOKEN_FILE = Path(__file__).resolve().parent.parent / ".github-token"

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
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
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
    for model in MODELS:
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({**body, "model": model}).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
            out = json.loads(resp["choices"][0]["message"]["content"])
            out["model"] = model
            return out
        except urllib.error.HTTPError as e:
            print(f"     {model} failed: HTTP {e.code} {e.read()[:200]!r}")
        except Exception as e:
            print(f"     {model} failed: {e}")
    return None


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
