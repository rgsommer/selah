#!/usr/bin/env python3
"""Re-pull photo submissions from Gmail without disturbing anything.

Re-scans the inbox (read AND unread), saving real photo/video attachments into
media/email/<Sender>/ — skipping bounce/mailer-daemon notices and files already
saved. It does NOT mark messages read (uses BODY.PEEK) and sends NO auto-replies,
so it's safe to re-run.

    python3 repull_emails.py                 # last 60 days
    python3 repull_emails.py 365             # last 365 days
    python3 repull_emails.py all             # entire inbox
"""

import os
import sys
import email
import imaplib
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.email_handler import (
    _is_bounce, _subject_caption, parse_subject_date, extract_caption,
    get_file_date, log_media, iter_media_parts, save_media_bytes,
)


def main():
    cfg = load_config("display_config.json")
    addr, pw = cfg.get("email_address"), cfg.get("email_password")
    if not addr or not pw:
        print("No email credentials configured.")
        return

    # Date window
    arg = (sys.argv[1] if len(sys.argv) > 1 else "60").lower()
    criteria = "ALL"
    if arg != "all":
        try:
            days = int(arg)
            since = (datetime.date.today() - datetime.timedelta(days=days))
            criteria = f'(SINCE {since.strftime("%d-%b-%Y")})'
            print(f"Scanning the last {days} days...")
        except ValueError:
            print("Usage: repull_emails.py [days|all]")
            return
    else:
        print("Scanning the ENTIRE inbox...")

    m = imaplib.IMAP4_SSL(cfg.get("imap_server", "imap.gmail.com"))
    m.login(addr, pw)
    m.select("inbox")
    _, data = m.search(None, criteria)
    nums = data[0].split()
    print(f"{len(nums)} message(s) to examine.")

    saved = skipped_existing = bounces = 0
    for num in nums:
        # BODY.PEEK[] fetches without setting the \Seen flag.
        _, md = m.fetch(num, "(BODY.PEEK[])")
        if not md or not md[0]:
            continue
        msg = email.message_from_bytes(md[0][1])
        sender = msg.get("from", "")
        subject = msg.get("subject", "")
        if _is_bounce(sender, subject, msg):
            bounces += 1
            continue

        caption = _subject_caption(subject)
        if not caption:
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        caption = extract_caption(part.get_payload(decode=True).decode(errors="replace"))
                    except Exception:
                        pass
                    break
        sdate = parse_subject_date(subject)

        for filename, data in iter_media_parts(msg):
            dest = save_media_bytes(data, filename, cfg, sender)
            if dest is None:                  # already had it (or error)
                skipped_existing += 1
                continue
            log_media(dest, sender, sdate or get_file_date(dest), caption or "")
            saved += 1
            print(f"  saved: {dest}")

    m.logout()
    print(f"\nDone. saved {saved} new photo(s); {skipped_existing} already had; "
          f"skipped {bounces} bounce/system message(s).")


if __name__ == "__main__":
    main()
