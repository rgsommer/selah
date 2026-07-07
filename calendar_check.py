#!/usr/bin/env python3
"""Show which Google calendars Selah pulls and how many events each has in the
agenda window (today+tomorrow) vs the coming week — so you can see whether a
'missing' calendar is skipped, erroring, or just has no near-term events.

    python3 calendar_check.py
"""

import os
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config


def main():
    cfg = load_config("display_config.json")
    if not os.path.exists("token.json"):
        print("No token.json — run:  python3 authorize.py")
        return
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as e:
        print("Google client libraries missing:", e)
        return

    creds = Credentials.from_authorized_user_file("token.json")
    svc = build("calendar", "v3", credentials=creds)
    now = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    def fetch(cid, days):
        end = now + datetime.timedelta(days=days)
        try:
            res = svc.events().list(
                calendarId=cid, timeMin=now.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=50).execute()
            return res.get("items", [])
        except Exception as e:
            return e

    use_all = cfg.get("calendar_use_all_calendars", True)
    print(f"calendar_use_all_calendars = {use_all}")
    print("on-screen agenda window = today + tomorrow (2 days)\n")

    cals = svc.calendarList().list().execute().get("items", [])
    for c in sorted(cals, key=lambda x: (not x.get("primary", False), x.get("summary", ""))):
        cid, name = c["id"], c.get("summary", "?")
        sel = c.get("selected", True)
        role = c.get("accessRole", "?")
        included = (sel is not False) if use_all else (cid == cfg.get("google_calendar_id", "primary"))
        ev2, ev7 = fetch(cid, 2), fetch(cid, 7)

        def cnt(x):
            return f"ERROR({x})" if isinstance(x, Exception) else str(len(x))
        tag = "shown" if sel is not False else "HIDDEN→skipped"
        inc = "PULLED " if included else "skipped"
        print(f"[{inc}] {name[:40]:40} ({tag}, {role})  {cnt(ev2)} in 2d / {cnt(ev7)} in 7d")
        if not isinstance(ev7, Exception):
            for e in ev7[:3]:
                s = e["start"].get("dateTime", e["start"].get("date"))
                print(f"        • {s}  {e.get('summary', '')}")

    print("\nOnly 'PULLED' calendars feed the agenda, and only their today/tomorrow")
    print("events appear on screen. '0 in 2d' but events in 7d = nothing near-term")
    print("(widen the window if you want the week — ask and I'll add agenda_days).")


if __name__ == "__main__":
    main()
