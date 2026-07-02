#!/usr/bin/env python3
"""Explain what the email checker sees — why a submission did or didn't save.

Read-only: uses BODY.PEEK (never marks mail read), saves nothing, replies to
nobody. For every recent message it prints the sender, how it's classified
(bounce / approval / opt-out / unapproved / normal), and every MIME part with
its content-type, size, and the exact reason it would be kept or skipped.

    python3 diagnose_email.py            # last 7 days
    python3 diagnose_email.py 30         # last 30 days
    python3 diagnose_email.py all        # entire inbox
"""

import os
import sys
import email
import imaplib
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.email_handler import (
    _is_bounce, _sender_folder, load_approved_senders,
    _IMG_MIME_EXT, _VID_MIME_EXT,
)

MIN_BYTES = 15000


def classify_parts(msg):
    """Return a list of (content_type, size, verdict) for every leaf part."""
    rows = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "").lower()
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        size = len(data)
        is_img = ctype in _IMG_MIME_EXT
        is_vid = ctype in _VID_MIME_EXT
        if is_img and size < MIN_BYTES:
            verdict = f"SKIP (image but only {size} B < {MIN_BYTES} min)"
        elif is_img or is_vid:
            verdict = "KEEP  <-- would be saved"
        elif ctype.startswith("image/") or ctype.startswith("video/"):
            verdict = f"SKIP (unrecognised media type '{ctype}')"
        else:
            verdict = "skip (not media)"
        rows.append((ctype, size, verdict))
    return rows


def main():
    cfg = load_config("display_config.json")
    addr, pw = cfg.get("email_address"), cfg.get("email_password")
    if not addr or not pw:
        print("No email credentials configured.")
        return

    arg = (sys.argv[1].lower() if len(sys.argv) > 1 else "7")
    criteria = "ALL"
    if arg != "all":
        try:
            days = int(arg)
            since = datetime.date.today() - datetime.timedelta(days=days)
            criteria = f'(SINCE {since.strftime("%d-%b-%Y")})'
            print(f"Scanning the last {days} days as {addr} ...\n")
        except ValueError:
            print("Usage: diagnose_email.py [days|all]")
            return
    else:
        print(f"Scanning the ENTIRE inbox as {addr} ...\n")

    try:
        m = imaplib.IMAP4_SSL(cfg.get("imap_server", "imap.gmail.com"))
        m.login(addr, pw)
    except Exception as e:
        print(f"LOGIN FAILED: {e}")
        print("-> This is why nothing saves: the checker can't sign in.")
        return
    m.select("inbox")

    approved = load_approved_senders()
    print(f"approved_senders.json: {approved if approved else 'empty (all senders allowed)'}\n")

    _, data = m.search(None, criteria)
    nums = data[0].split()
    print(f"{len(nums)} message(s) in window.\n" + "=" * 64)

    would_save = 0
    for num in nums:
        _, md = m.fetch(num, "(BODY.PEEK[])")
        if not md or not md[0]:
            continue
        msg = email.message_from_bytes(md[0][1])
        sender = msg.get("from", "")
        subject = msg.get("subject", "")
        date = msg.get("date", "")

        print(f"\nFROM:    {sender}")
        print(f"SUBJECT: {subject}")
        print(f"DATE:    {date}")
        print(f"folder:  media/email/{_sender_folder(sender)}/")

        if _is_bounce(sender, subject, msg):
            print("CLASS:   BOUNCE / system mail  -> skipped, nothing saved")
            continue
        if approved and not any(s in sender for s in approved):
            print("CLASS:   UNAPPROVED sender -> routed to owner approval, "
                  "NOT saved to media/email")
            # still show parts so you can see the photos are there
        else:
            print("CLASS:   normal submission")

        rows = classify_parts(msg)
        media_rows = [r for r in rows if "KEEP" in r[2] or "SKIP (image" in r[2]
                      or "unrecognised" in r[2]]
        if not media_rows:
            print("  parts: no image/video parts found at all "
                  "(sent as a link? shared album? forwarded inline?)")
        for ctype, size, verdict in rows:
            if verdict == "skip (not media)":
                continue
            print(f"  part: {ctype:<16} {size:>9,} B  {verdict}")
        if any("KEEP" in r[2] for r in rows) and not (
                approved and not any(s in sender for s in approved)):
            would_save += 1

    m.logout()
    print("\n" + "=" * 64)
    print(f"{would_save} message(s) would save a photo right now.")
    print("(read-only: nothing was saved, marked read, or replied to)")


if __name__ == "__main__":
    main()
