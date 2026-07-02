#!/usr/bin/env python3
"""Report the inactivity-nudge schedule: who's due, and when the next one fires.

Read-only — sends nothing. Reads approved_senders.json, nudge_log.json,
media_log.json and the config to reproduce exactly what send_inactivity_nudges
would decide on its next daily scan.

    python3 nudge_status.py
"""

import os
import json
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.email_handler import (
    load_approved_senders, load_nudge_optout, _last_submission_by_email,
    NUDGE_LOG_FILE,
)


def main():
    cfg = load_config("display_config.json")
    now = datetime.datetime.now()
    weeks = int(cfg.get("nudge_inactive_weeks", 4))
    gap = datetime.timedelta(weeks=max(1, weeks))

    if not cfg.get("nudge_enabled", True):
        print("Nudges are DISABLED (nudge_enabled = false). No nudges will be sent.")
        return

    owner = cfg.get("email_address", "")
    senders = load_approved_senders()
    optout = load_nudge_optout()
    last_sub = _last_submission_by_email()
    try:
        with open(NUDGE_LOG_FILE) as f:
            nlog = json.load(f)
    except Exception:
        nlog = {}

    print(f"Inactivity window: {weeks} week(s)   ·   scan runs once per day")
    last_run = nlog.get("_last_run", "")
    if last_run[:10] == now.date().isoformat():
        print(f"Today's scan already ran at {last_run[:19]} — next scan is tomorrow.")
    else:
        print("Today's scan has NOT run yet — it will on the next email check.")
    print(f"Approved senders: {len(senders)}\n")

    if not senders:
        print("No approved senders configured — nudges only go to that list, so none will send.")
        return

    def parse(ts):
        try:
            return datetime.datetime.fromisoformat(ts)
        except Exception:
            return None

    rows = []
    for s in senders:
        if s == owner:
            continue
        if s.lower() in optout:
            rows.append((None, s, "opted out (replied 'stop')"))
            continue
        ls = last_sub.get(s)
        ln = parse(nlog.get(s, ""))
        # Next eligible = when both 'quiet since last submission' and 'not nudged
        # recently' are satisfied. Never-submitted/never-nudged => due now.
        anchors = [t for t in (ls, ln) if t is not None]
        due = max(a + gap for a in anchors) if anchors else now
        when = "DUE NOW (next scan)" if due <= now else due.strftime("%b %-d, %Y")
        detail = []
        detail.append(f"last photo {ls.strftime('%b %-d') if ls else 'never'}")
        detail.append(f"last nudged {ln.strftime('%b %-d') if ln else 'never'}")
        rows.append((due if due > now else now, s, f"{when}  ({', '.join(detail)})"))

    rows.sort(key=lambda r: (r[0] is None, r[0] or now))
    for _due, s, msg in rows:
        print(f"  {s:<32} {msg}")

    upcoming = [r[0] for r in rows if r[0] is not None]
    if upcoming:
        nxt = min(upcoming)
        if nxt <= now:
            print(f"\nNext nudge: on the next daily scan "
                  f"({'today' if last_run[:10] != now.date().isoformat() else 'tomorrow'}).")
        else:
            print(f"\nNext nudge: {nxt.strftime('%b %-d, %Y')} "
                  f"(in {(nxt - now).days} day(s)).")


if __name__ == "__main__":
    main()
