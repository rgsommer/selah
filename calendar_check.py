#!/usr/bin/env python3
"""Diagnose the calendar agenda: which Google ACCOUNT the token belongs to,
which calendars are pulled vs skipped, and the ACTUAL events in the window.

    python3 calendar_check.py            # window = agenda_days from config
    python3 calendar_check.py 5          # force a 5-day window
    python3 calendar_check.py 5 --all    # include hidden (unchecked) calendars too

If you expect events but see none, check the "Token account" line first — if it
isn't the account whose calendars you want, re-run:  python3 authorize.py
"""

import os
import sys
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config


def main():
    cfg = load_config("display_config.json")
    args = sys.argv[1:]
    include_hidden = "--all" in args
    days = next((int(a) for a in args if a.isdigit()), None) or max(1, int(cfg.get("agenda_days", 3)))

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
    if not creds or not creds.valid:
        try:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        except Exception as e:
            print(f"Token invalid and refresh failed: {e}\nRe-run: python3 authorize.py")
            return
    svc = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + datetime.timedelta(days=days)

    cals = svc.calendarList().list().execute().get("items", [])
    account = next((c["id"] for c in cals if c.get("primary")), "?")
    use_all = cfg.get("calendar_use_all_calendars", True)

    print(f"Token account : {account}")
    print(f"agenda_days   : {cfg.get('agenda_days', 3)}   (checking {days}-day window: "
          f"{now.date()} -> {end.date()})")
    print(f"use_all_cals  : {use_all}    include_hidden(--all) : {include_hidden}")
    print(f"{len(cals)} calendar(s) visible to this token.\n")

    def fetch(cid):
        try:
            res = svc.events().list(
                calendarId=cid, timeMin=now.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=250).execute()
            return res.get("items", [])
        except Exception as e:
            return e

    grand = 0
    for c in sorted(cals, key=lambda x: (not x.get("primary", False), x.get("summary", ""))):
        cid, name = c["id"], c.get("summary", "?")
        sel = c.get("selected", True)
        role = c.get("accessRole", "?")
        pulled = (sel is not False) if use_all else (cid == cfg.get("google_calendar_id", "primary"))
        probe = pulled or include_hidden
        state = "PULLED " if pulled else ("hidden " if sel is False else "skipped")

        evs = fetch(cid) if probe else None
        if isinstance(evs, Exception):
            print(f"[{state}] {name[:44]:44}  ERROR: {evs}")
            continue
        n = len(evs) if evs is not None else "-"
        print(f"[{state}] {name[:44]:44} ({role})  {n} event(s) in {days}d")
        if evs:
            if pulled:
                grand += len(evs)
            for e in evs:
                s = e["start"].get("dateTime", e["start"].get("date"))
                loc = f"  @ {e.get('location')}" if e.get("location") else ""
                print(f"        - {s[:16]:16}  {e.get('summary', '(no title)')}{loc}")

    print(f"\nTOTAL events feeding the on-screen agenda: {grand} "
          f"(from PULLED calendars, next {days} days).")
    if grand == 0:
        print("\n0 events. Most likely one of:")
        print(f"  1. Wrong account — 'Token account' above is {account}; if that's not the")
        print("     one with your events, run:  python3 authorize.py  (sign in as that account)")
        print("  2. Your events live on calendars marked 'hidden' (unchecked in Google")
        print("     Calendar) — re-run with --all to see them, then tick them in Google.")
        print("  3. They're truly outside the window — widen it: python3 calendar_check.py 14")


if __name__ == "__main__":
    main()
