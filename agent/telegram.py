"""Sends the Global Market Radar to Telegram after each run (free, via your own bot).

Needs two GitHub repository secrets:
  TELEGRAM_BOT_TOKEN  the bot's token from @BotFather
  TELEGRAM_CHAT_ID    who receives it: your chat id, or several separated by commas (e.g. family)
Without them this does nothing.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from html import escape

LIMIT = 4096  # Telegram's maximum message length
TONE = {"good": "🟢", "watch": "🟠", "bad": "🔴"}
KEY = [("Nasdaq", "Nasdaq"), ("S&P 500", "S&P 500"), ("Philadelphia Semiconductor index", "Chips"),
       ("Brent crude (US$/barrel)", "Brent"), ("Gold (US$/oz)", "Gold"),
       ("USD/MYR", "USD/MYR"), ("FBM KLCI", "KLCI")]


def tone(t) -> str:
    return TONE.get(str(t).strip().lower(), "⚪")


def numbers(radar: dict) -> str:
    by = {m["label"]: m for m in radar["markets"] if m.get("last") is not None}
    out = []
    for label, short in KEY:
        m = by.get(label)
        if not m:
            continue
        if m.get("change_pct") is None:
            out.append(f"{short} {m['last']:.2f}% ({m['change'] * 100:+.0f}bp)")
        else:
            out.append(f"{short} {m['last']:,.2f} ({m['change_pct']:+.2f}%)")
    return " · ".join(out)


def opening(radar: dict) -> str:
    o = radar.get("bursa_open") or {}
    if not o.get("traded_today") or "Morning" not in radar["edition"]:
        return ""
    b = radar.get("bursa") or {}
    breadth = f"\n{b['gainers']} gainers, {b['losers']} losers so far" if b else ""
    return (f"🔔 <b>Bursa's start</b>: KLCI opened {o['open']:,.2f} ({o['open_pct']:+.2f}%), "
            f"now {o['now']:,.2f} ({o['now_pct']:+.2f}%){breadth}")


def messages(radar: dict, site: str) -> list:
    a = radar["ai"]
    e = lambda s: escape(str(s or ""))
    parts = [
        f"<b>🌏 Global Market Radar: What Matters for Bursa</b>\n<i>{e(radar['date'])} · {e(radar['edition'])}</i>",
        e(numbers(radar)),
        opening(radar),
        (f"<b>{e(a['headline'])}</b>\n" if a.get("headline") else "") + e(a.get("intro")),
    ]
    for i, it in enumerate(a.get("items", []), 1):
        parts.append(f"{tone(it.get('tone'))} <b>{i}. {e(it.get('headline'))}</b>"
                     + (f"  <i>[{e(it['category'])}]</i>" if it.get("category") else "")
                     + f"\n{e(it.get('what_happened'))}"
                     + (f"\n<b>Why:</b> {e(it['why'])}" if it.get("why") else "")
                     + (f"\n🔗 <code>{e(it['chain']).replace('-&gt;', '→')}</code>" if it.get("chain") else "")
                     + f"\n🇲🇾 <i>Malaysia angle:</i> {e(it.get('malaysia_angle'))}")
    if a.get("movers"):
        parts.append("🔥 <b>Big movers</b>\n" + "\n".join(f"• {e(m.get('name'))} <b>{e(m.get('move'))}</b>: {e(m.get('why'))}" for m in a["movers"]))
    if a.get("watching"):
        parts.append("📌 <b>Coming up</b>\n" + "\n".join(f"• {e(w.get('label'))}: {e(w.get('value'))}" for w in a["watching"]))
    bottom = "\n".join(f"{e(b.get('text'))} {tone(b.get('tone'))}" for b in a.get("bottom_line", []))
    parts.append(f"<b>Bottom line</b>\n{bottom}\n\n{e(a.get('summary'))}"
                 + (f"\n\n<b>For Bursa:</b> {e(a['bursa_focus'])}" if a.get("bursa_focus") else ""))
    parts.append(f'<a href="{e(site)}">Open the full dashboard</a> · AI-written from Yahoo Finance and news headlines. Not financial advice.')
    return split(parts)


def split(parts: list) -> list:
    """Long days are split into several messages at paragraph breaks."""
    chunks = [""]
    for p in filter(None, parts):
        if chunks[-1] and len(chunks[-1]) + len(p) + 2 > LIMIT:
            chunks.append("")
        chunks[-1] += ("\n\n" if chunks[-1] else "") + p
    return chunks


def digest(radar: dict, site: str) -> list:
    """Plain numbers and headlines, for when the AI is unavailable."""
    e = lambda s: escape(str(s or ""))
    parts = [f"<b>🌏 Global Market Radar: numbers only</b>\n<i>{e(radar['date'])} · {e(radar['edition'])}</i>",
             "⚠️ Google's free AI is overloaded, so there's no write-up yet. A later attempt will send it if the AI recovers.",
             e(numbers(radar)), opening(radar)]
    parts = [p for p in parts if p]
    us = (radar.get("us") or {}).get("big_movers_last_session") or []
    if us:
        parts.append("🔥 <b>US big movers</b>\n" + "\n".join(f"• {e(m['name'])} <b>{m['change_pct']:+.1f}%</b>" for m in us[:8]))
    b = radar.get("bursa") or {}
    if b:
        parts.append(f"🇲🇾 <b>Bursa</b>: {b['gainers']} gainers, {b['losers']} losers\n"
                     + "\n".join(f"• {e(k)} {v['average_pct']:+.2f}%" for k, v in (b.get("sectors") or {}).items()))
    if radar.get("news"):
        parts.append("📰 <b>Headlines</b>\n" + "\n".join(
            f'• <a href="{e(n["link"])}">{e(n["title"])}</a> ({e(n["source"])})' for n in radar["news"][:6]))
    parts.append(f'<a href="{e(site)}">Open the dashboard</a>')
    return split(parts)


def send_radar(radar: dict, site: str, quiet: bool = False) -> bool:
    """True if every chat received it. quiet: send only a full write-up, not a fallback."""
    token, chats = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chats.strip():
        print("TG   skipped (no Telegram secrets)")
        return False
    if (radar or {}).get("ai"):
        texts = messages(radar, site)
    elif quiet:
        print("TG   no write-up again; the numbers were already sent")
        return False
    elif radar:
        print("TG   no write-up; sending the numbers")
        texts = digest(radar, site)
    else:
        texts = [f'⚠️ Today\'s Market Radar couldn\'t be built. Another attempt follows. <a href="{escape(site)}">Open the dashboard</a>']
    ok = True
    for chat in (c.strip() for c in chats.split(",") if c.strip()):
        try:
            for text in texts:
                body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                               "disable_web_page_preview": "true"}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30)
            print(f"TG   radar sent ({len(texts)} message(s))")
        except urllib.error.HTTPError as err:
            # Never print the token or chat id: the logs of a public repo are public
            ok = False
            print(f"TG   send failed: HTTP {err.code} {json.loads(err.read() or b'{}').get('description', '')}")
        except Exception as err:
            ok = False
            print(f"TG   send failed: {type(err).__name__}")
    return ok
