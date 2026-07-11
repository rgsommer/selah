#!/usr/bin/env python3
"""Restore approved senders that were removed (e.g. un-approved before the
'blocked' state existed). Gathers every email address Selah has ever seen —
from contacts.json, media_log.json (past submitters), and pending_approvals.json
— and shows the ones NOT currently approved so you can re-add them.

    python3 restore_senders.py                 # list restorable addresses
    python3 restore_senders.py --all           # re-approve ALL of them
    python3 restore_senders.py a@x.com b@y.com # re-approve just these
"""

import os
import sys
import json
from email.utils import parseaddr

os.chdir(os.path.dirname(os.path.abspath(__file__)))

APPROVED = "approved_senders.json"


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _addr(s):
    _, a = parseaddr(s or "")
    return a.strip().lower()


def main():
    args = [a for a in sys.argv[1:] if a]
    do_all = "--all" in args
    picks = {a.lower() for a in args if "@" in a}

    approved = [str(s).strip() for s in _load(APPROVED, []) if str(s).strip()]
    approved_l = {s.lower() for s in approved}

    # Known addresses -> a friendly source note and best name.
    known = {}   # email -> {"name":.., "sources":set()}

    def note(email, name, src):
        email = (email or "").strip()
        if not email or "@" not in email:
            return
        d = known.setdefault(email.lower(), {"email": email, "name": "", "sources": set()})
        if name and not d["name"]:
            d["name"] = name
        d["sources"].add(src)

    for c in _load("contacts.json", []):
        if isinstance(c, dict):
            note(c.get("email", ""), c.get("name", ""), "contacts")
    for e in _load("media_log.json", []):
        s = e.get("sender", "") if isinstance(e, dict) else ""
        note(_addr(s), (s.split("<")[0].strip().strip('"') if "<" in s else ""), "submitted photos")
    for e in _load("pending_approvals.json", []):
        if isinstance(e, dict):
            note(e.get("sender_email", ""), e.get("sender_name", ""), "pending")

    # Restorable = known but not currently approved.
    restorable = {k: v for k, v in known.items() if k not in approved_l}
    if not restorable:
        print("Nothing to restore — every known address is already approved.")
        return

    ordered = sorted(restorable.values(), key=lambda v: v["email"].lower())

    if not do_all and not picks:
        print(f"{len(ordered)} address(es) not currently approved:\n")
        for v in ordered:
            nm = f"{v['name']}  " if v["name"] else ""
            print(f"   {nm}<{v['email']}>   ({', '.join(sorted(v['sources']))})")
        print("\nRe-approve all:   python3 restore_senders.py --all")
        print("Re-approve some:  python3 restore_senders.py " + ordered[0]["email"]
              + (" " + ordered[1]["email"] if len(ordered) > 1 else ""))
        return

    to_add = [v["email"] for v in ordered
              if do_all or v["email"].lower() in picks]
    if not to_add:
        print("None of those addresses matched the restorable list.")
        return
    for em in to_add:
        approved.append(em)
    json.dump(approved, open(APPROVED, "w"), indent=2)
    print(f"Re-approved {len(to_add)} sender(s):")
    for em in to_add:
        print(f"   + {em}")


if __name__ == "__main__":
    main()
