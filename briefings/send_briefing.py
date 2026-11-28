"""Sends the daily stock briefing to Telegram, through the same bot as the Bursa watchlist radar.

A Claude scheduled task gathers the data from the moomoo MCP (read-only), writes the briefing
as JSON, and runs this script. The briefing never contains P&L or money amounts of the holdings.

    python3 -I send_briefing.py briefing.json            # sends
    python3 -I send_briefing.py briefing.json --dry-run  # prints instead

The layout is built here, so the JSON only holds short facts:
{
  "date": "Fri 27 Nov",
  "quick":  [{"tone": "down|up|flat", "short": "AAGB", "change": "−5.3%", "text": "big money still selling"}],
  "watch":  ["AAGB leaves the MSCI small-cap index at Monday's close → heavy selling likely late in the day"],
  "stocks": [{"emoji": "✈️", "short": "AAGB", "name": "AirAsia", "price": "0.445", "change": "−5.3%", "tone": "down",
              "volume": "Normal", "players": "Selling · 7 of last 10 days", "trend": "Near month low (0.415)",
              "takeaway": "Last week's bounce fully given back",
              "details": ["Moves with jet fuel and the ringgit", "..."]}]
}
Plain text only; everything is escaped here. "details" is shown folded (tap to expand).

The bot token and chat id are read from the macOS Keychain (service bursa-telegram-bot,
accounts token and chat_id); save_telegram_keys.sh stores them on the Mac; in the cloud they come from the environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import escape

LIMIT = 4096
DOT = {"up": "🟢", "down": "🔴", "flat": "⚪"}
LINE = "━━━━━━━━━━━━━━"


def keychain(account: str) -> str:
    """In the cloud the values come from environment variables; on the Mac from the Keychain."""
    env = os.environ.get({"token": "TELEGRAM_BOT_TOKEN", "chat_id": "TELEGRAM_CHAT_ID"}[account], "").strip()
    if env:
        return env
    if sys.platform != "darwin":
        sys.exit(f"Missing environment variable for {account}: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                 "in the cloud environment's settings")
    r = subprocess.run(["security", "find-generic-password", "-s", "bursa-telegram-bot", "-a", account, "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Keychain item bursa-telegram-bot/{account} is missing. Run: zsh save_telegram_keys.sh")
    return r.stdout.strip()


def e(s) -> str:
    return escape(str(s or ""), quote=False)


def dot(tone) -> str:
    return DOT.get(str(tone).lower(), "⚪")


def stock_card(s: dict) -> str:
    rows = [f"{s.get('emoji', '📈')} <b>{e(s.get('short'))}</b> · {e(s.get('name'))}",
            f"<b>{e(s.get('price'))}</b>  {dot(s.get('tone'))} {e(s.get('change'))}", ""]
    if s.get("rows"):  # free rows, e.g. for the pre-open briefing
        rows += [f"{r.get('icon', '•')} {e(r.get('label'))}: {e(r.get('value'))}" for r in s["rows"]]
    for icon, label, key in (("📦", "Volume", "volume"), ("🐋", "Big players", "players"), ("📈", "Trend", "trend")):
        if s.get(key):
            rows.append(f"{icon} {label}: {e(s[key])}")
    if s.get("takeaway"):
        rows += ["", f"💡 <i>{e(s['takeaway'])}</i>"]
    if s.get("details"):
        rows.append("<blockquote expandable>" + "\n".join(f"• {e(d)}" for d in s["details"]) + "</blockquote>")
    return "\n".join(rows)


def render(b: dict) -> list:
    top = [f"{e(b.get('title') or '📊 Your stocks')} · {e(b.get('date'))}"]
    top[0] = f"<b>{top[0]}</b>"
    if b.get("us"):  # pre-open: the last US session, one line per market
        top += ["", "<b>🇺🇸 Overnight in the US</b>"] + [
            f"{dot(u.get('tone'))} {e(u.get('label'))} {e(u.get('change'))}" + (f" · {e(u['note'])}" if u.get("note") else "")
            for u in b["us"]]
        if b.get("us_note"):
            top.append(f"💡 <i>{e(b['us_note'])}</i>")
    if b.get("quick"):
        top += ["", f"<b>{e(b.get('quick_title') or '⚡ In 10 seconds')}</b>"] + [
            f"{dot(q.get('tone'))} <b>{e(q.get('short'))}</b>" + (f" {e(q['change'])}" if q.get("change") else "")
            + f" · {e(q.get('text'))}" for q in b["quick"]]
    if b.get("watch"):
        top += ["", "<b>⚠️ Watch</b>"] + [f"• {e(w)}" for w in b["watch"]]
    parts = ["\n".join(top)] + [f"{LINE}\n{stock_card(s)}" for s in b.get("stocks", [])]
    parts.append(f"{LINE}\n<i>Facts to watch, not advice · delayed prices · tap a ▸ quote to see more</i>")
    chunks = [""]
    for p in parts:  # long days split into several messages between stocks
        if chunks[-1] and len(chunks[-1]) + len(p) + 2 > LIMIT:
            chunks.append("")
        chunks[-1] += ("\n\n" if chunks[-1] else "") + p[:LIMIT]
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("briefing_json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with open(args.briefing_json) as f:
        texts = render(json.load(f))
    if args.dry_run:
        print("\n\n----- next message -----\n\n".join(texts))
        return
    token, ok = keychain("token"), True
    for chat in (c.strip() for c in keychain("chat_id").split(",") if c.strip()):
        for text in texts:
            body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                           "disable_web_page_preview": "true"}).encode()
            try:
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30)
            except urllib.error.HTTPError as err:  # never print the token or chat id
                ok = False
                print(f"send failed: HTTP {err.code} {json.loads(err.read() or b'{}').get('description', '')}")
            except Exception as err:
                ok = False
                print(f"send failed: {type(err).__name__}")
    print(f"sent ({len(texts)} message(s))" if ok else "not sent to every chat")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
