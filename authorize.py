#!/usr/bin/env python3
"""(Re)authorize Google access for Selah — Drive + Calendar (read-only).

Run this to point Selah at the RIGHT account and grant the RIGHT scopes. It
backs up any old token, runs the Google consent flow in a browser, writes a
fresh token.json, then lists every calendar the account can see (so you can
confirm your subscribed ones are 'shown', not hidden).

    python3 authorize.py

Sign in with the account whose calendars/photos you want (e.g.
pngsommers@gmail.com) and grant BOTH Calendar and Drive when asked.
"""

import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from modules.google_drive_sync import SCOPES

CRED = "credentials.json"
TOK = "token.json"


def main():
    if not os.path.exists(CRED):
        print("Missing credentials.json — download an OAuth Desktop client from "
              "the Google Cloud Console and save it here as credentials.json.")
        return
    if os.path.exists(TOK):
        os.replace(TOK, TOK + ".bak")
        print("Backed up existing token.json -> token.json.bak")

    print("Scopes being requested:")
    for s in SCOPES:
        print("   ", s)
    flow = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOK, "w") as f:
        f.write(creds.to_json())
    print("\nWrote token.json ✔")

    try:
        svc = build("calendar", "v3", credentials=creds)
        cals = svc.calendarList().list().execute().get("items", [])
        print(f"\nThis account can see {len(cals)} calendar(s):")
        for c in sorted(cals, key=lambda x: (not x.get("primary", False), x.get("summary", ""))):
            tag = "PRIMARY" if c.get("primary") else ("shown" if c.get("selected", True)
                                                      else "HIDDEN — will NOT display")
            print(f"   - {c.get('summary', '?'):40} [{tag}]")
        print("\nCalendars marked HIDDEN are unchecked in Google Calendar; check "
              "them there to include their events.")
    except Exception as e:
        print("Authorized, but couldn't list calendars (is the Calendar scope "
              f"granted?): {e}")


if __name__ == "__main__":
    main()
