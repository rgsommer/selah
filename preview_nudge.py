#!/usr/bin/env python3
"""Preview (or test-send) the enhanced inactivity-nudge email.

    python3 preview_nudge.py            # write nudge_preview.html (open in a browser)
    python3 preview_nudge.py --send     # ALSO email a live sample to yourself (the
                                        # owner address), bypassing throttle/approval

The preview embeds the most-recently-submitted photo (from media_log.json) as
the "Remember this one?" thumbnail, so you see exactly what a real recipient gets.
It changes nothing else — no throttle state is touched and no one else is emailed.
"""

import os
import sys
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.email_handler import (
    _nudge_html, _thumbnail_bytes, _last_photo_by_email,
    NUDGE_BODY, NUDGE_SUBJECT,
)


def main():
    cfg = load_config("display_config.json")
    owner = cfg.get("email_address", "")
    owner_name = cfg.get("display_owner_name", "the family display")
    name = (owner.split("@")[0].replace(".", " ").replace("_", " ").title()
            if owner else "Friend")

    # Use the newest logged photo as the sample thumbnail.
    latest = _last_photo_by_email()
    path = caption = None
    if owner in latest:
        path, caption = latest[owner]
    else:
        for _addr, (p, c) in latest.items():
            path, caption = p, c
            break
    thumb = _thumbnail_bytes(path, size=230) if path else None
    caption = caption or ""

    html = _nudge_html(name, owner_name, bool(thumb), caption)

    # For the browser preview, inline the thumbnail as a data URI (cid: won't render).
    browser_html = html
    if thumb:
        b64 = base64.b64encode(thumb).decode()
        browser_html = html.replace("cid:lastphoto", f"data:image/jpeg;base64,{b64}")
    with open("nudge_preview.html", "w") as f:
        f.write(browser_html)
    print("Wrote nudge_preview.html")
    print(f"  subject: {NUDGE_SUBJECT.replace('{name}', name).replace('{owner}', owner_name)}")
    print(f"  thumbnail: {'yes — ' + path if thumb else 'none (no logged photos yet)'}")

    if "--send" in sys.argv:
        if not owner or not cfg.get("email_password"):
            print("No email credentials — can't send.")
            return
        msg = MIMEMultipart("related")
        msg["Subject"] = "[SAMPLE] " + NUDGE_SUBJECT.replace("{name}", name).replace("{owner}", owner_name)
        msg["From"] = owner
        msg["To"] = owner
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(NUDGE_BODY.replace("{name}", name).replace("{owner}", owner_name), "plain"))
        alt.attach(MIMEText(html, "html"))
        msg.attach(alt)
        if thumb:
            img = MIMEImage(thumb, "jpeg")
            img.add_header("Content-ID", "<lastphoto>")
            img.add_header("Content-Disposition", "inline", filename="lastphoto.jpg")
            msg.attach(img)
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(owner, cfg["email_password"])
            server.send_message(msg)
        print(f"Sent a sample nudge to {owner}")


if __name__ == "__main__":
    main()
