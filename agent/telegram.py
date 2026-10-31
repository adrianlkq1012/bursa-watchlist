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
       ("Brent crude (US$/barrel)", "Brent"), ("US 10-year Treasury yield (%)", "US 10Y"),
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


def messages(radar: dict, site: str) -> list:
    a = radar["ai"]
    e = lambda s: escape(str(s or ""))
    parts = [
        f"<b>🌏 Global Market Radar: What Matters for Bursa</b>\n<i>{e(radar['date'])} · {e(radar['edition'])}</i>",
        e(numbers(radar)),
        e(a.get("intro")),
    ]
    for i, it in enumerate(a.get("items", []), 1):
        parts.append(f"{tone(it.get('tone'))} <b>{i}. {e(it.get('headline'))}</b>\n"
                     + " ".join(e(p) for p in it.get("points", []))
                     + f"\n🇲🇾 <i>Malaysia angle:</i> {e(it.get('malaysia_angle'))}")
    if a.get("watching"):
        parts.append("📌 <b>What to watch next</b>\n" + "\n".join(f"• {e(w.get('label'))}: {e(w.get('value'))}" for w in a["watching"]))
    bottom = "\n".join(f"{e(b.get('text'))} {tone(b.get('tone'))}" for b in a.get("bottom_line", []))
    parts.append(f"<b>Bottom line</b>\n{bottom}\n\n{e(a.get('summary'))}"
                 + (f"\n\n<b>For Bursa:</b> {e(a['bursa_focus'])}" if a.get("bursa_focus") else ""))
    parts.append(f'<a href="{e(site)}">Open the full dashboard</a> · AI-written from Yahoo Finance and news headlines. Not financial advice.')
    # Long days are split into several messages at paragraph breaks
    chunks = [""]
    for p in filter(None, parts):
        if chunks[-1] and len(chunks[-1]) + len(p) + 2 > LIMIT:
            chunks.append("")
        chunks[-1] += ("\n\n" if chunks[-1] else "") + p
    return chunks


def send_radar(radar: dict, site: str) -> None:
    token, chats = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chats.strip():
        print("TG   skipped (no Telegram secrets)")
        return
    if not (radar or {}).get("ai"):
        print("TG   skipped (no radar write-up this run)")
        return
    texts = messages(radar, site)
    for chat in (c.strip() for c in chats.split(",") if c.strip()):
        try:
            for text in texts:
                body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                               "disable_web_page_preview": "true"}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30)
            print(f"TG   radar sent ({len(texts)} message(s))")
        except urllib.error.HTTPError as err:
            # Never print the token or chat id: the logs of a public repo are public
            print(f"TG   send failed: HTTP {err.code} {json.loads(err.read() or b'{}').get('description', '')}")
        except Exception as err:
            print(f"TG   send failed: {type(err).__name__}")
