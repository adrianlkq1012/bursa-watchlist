"""Decides whether a scheduled run still has work to do (standard library only).

GitHub sometimes starts scheduled runs hours late or drops them, and the free AI is sometimes
overloaded, so daily.yml schedules several attempts per edition. The published status.json says
which edition was last delivered; attempts after a delivered one stop here.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8))
SITE = "https://adrianlkq1012.github.io/bursa-watchlist/"


def edition(now: datetime):
    """The edition a run at this time belongs to, or None if it's too late or early to be useful."""
    if now.weekday() >= 5:
        return f"{now:%Y-%m-%d} weekend"
    if now.hour < 5:
        return None  # a badly delayed evening run; Wall Street is still trading
    return f"{now:%Y-%m-%d} {'morning' if now.hour < 17 else 'evening'}"


def published() -> dict:
    for wait in (0, 5, 15, 30):
        time.sleep(wait)
        try:
            req = urllib.request.Request(f"{SITE}status.json?t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception as e:
            print(f"DUE  no published status ({e})")
    return {}  # better a repeated message than a missing one


def due(now: datetime, event: str, status: dict) -> bool:
    if event != "schedule":
        return True  # manual and deep-dive runs always go ahead
    ed = edition(now)
    if ed is None or ed.endswith("weekend"):
        return False  # Saturday's edition comes from the deep-dive run
    return not (status.get("edition") == ed and status.get("delivered"))


if __name__ == "__main__":
    now = datetime.now(MYT)
    go = due(now, os.environ.get("GITHUB_EVENT_NAME", ""), published())
    print(f"DUE  {edition(now)}: {'running' if go else 'nothing to do'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"run={'true' if go else 'false'}\n")
