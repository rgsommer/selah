"""Email intake: checks IMAP for new photos/videos, saves attachments,
sends auto-replies, and coordinates with leaderboard/backup/toast modules."""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import parsedate_to_datetime, parseaddr
import io
import hashlib
import modules.heif_support  # noqa: F401  (HEIC thumbnails)
from pathlib import Path
import re
import datetime
import json
import time
import os
from modules.logger import log_error

# Re-export log_error so existing imports from modules.email_handler still work
__all__ = ["check_for_new_emails", "log_error"]


PROCESSED_FILE = "processed_emails.json"


def _load_processed():
    """(processed {message_id: iso}, file_existed). We track handled emails
    ourselves so intake never depends on the unread flag."""
    try:
        with open(PROCESSED_FILE) as f:
            return json.load(f), True
    except FileNotFoundError:
        return {}, False
    except Exception:
        return {}, True   # corrupt -> don't re-seed (avoids a reply flood)


def _save_processed(d):
    try:
        with open(PROCESSED_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        log_error(f"Failed to save {PROCESSED_FILE}: {e}")


def _prune_processed(d, days):
    """Drop entries older than `days` (kept well beyond the search window so
    nothing is ever reprocessed)."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    for mid in list(d):
        try:
            if datetime.datetime.fromisoformat(d[mid]) < cutoff:
                del d[mid]
        except Exception:
            del d[mid]


def _msg_id(msg):
    """A stable key for an email: its Message-ID, else a from+subject+date hash."""
    if msg is None:
        return None
    mid = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    if mid:
        return mid
    key = f"{msg.get('From', '')}|{msg.get('Subject', '')}|{msg.get('Date', '')}"
    return "fallback:" + hashlib.md5(key.encode("utf-8", "replace")).hexdigest()


def check_for_new_emails(config, screens):
    """Process every recent email we haven't handled yet, tracked by Message-ID
    (not the unread flag), so a network blip or an email opened in Gmail can never
    make a submission slip through. Read state is left untouched (BODY.PEEK)."""
    if not config.get("email_address") or not config.get("email_password"):
        return
    if config.get("email_password") == "your-app-specific-password":
        return  # Placeholder password, skip

    lookback = max(1, int(config.get("email_lookback_days", 7)))
    processed, existed = _load_processed()
    now_iso = datetime.datetime.now().isoformat()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            mail = imaplib.IMAP4_SSL(config["imap_server"])
            mail.login(config["email_address"], config["email_password"])
            mail.select("inbox")

            since = (datetime.date.today()
                     - datetime.timedelta(days=lookback)).strftime("%d-%b-%Y")
            _, data = mail.search(None, f'(SINCE {since})')
            nums = data[0].split() if data and data[0] else []

            seeded = handled = 0
            for num in nums:
                # Cheap header fetch for the Message-ID (does not mark read).
                _, hd = mail.fetch(
                    num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])")
                hdr = (email.message_from_bytes(hd[0][1])
                       if hd and hd[0] else None)
                mid = _msg_id(hdr) or f"uid:{num.decode() if isinstance(num, bytes) else num}"
                if mid in processed:
                    continue
                # First run: seed already-handled (read) mail without acting, so
                # we don't re-reply; only act on still-unread mail.
                if not existed:
                    _, fl = mail.fetch(num, "(FLAGS)")
                    if fl and fl[0] and b"\\Seen" in fl[0]:
                        processed[mid] = now_iso
                        seeded += 1
                        continue
                # Fetch the full message and handle it (still no read-flag change).
                _, full = mail.fetch(num, "(BODY.PEEK[])")
                if full and full[0]:
                    _process_email(email.message_from_bytes(full[0][1]), config, screens)
                    handled += 1
                processed[mid] = now_iso

            if not existed and seeded:
                print(f"[Selah] Email intake: seeded {seeded} already-handled message(s)")
            if handled:
                print(f"[Selah] Email intake: handled {handled} new message(s)")
            _prune_processed(processed, max(30, lookback * 3))
            _save_processed(processed)
            mail.logout()
            break

        except Exception as e:
            # Transient network/DNS blips aren't real failures — don't email the
            # owner or toast a scary message for them; only genuine errors (bad
            # credentials, etc.) are critical.
            msg = str(e).lower()
            transient = any(t in msg for t in (
                "name resolution", "temporary failure", "temporarily",
                "timed out", "timeout", "connection reset", "connection refused",
                "network is unreachable", "broken pipe", "errno -3"))
            is_last = attempt == max_retries - 1
            error_msg = f"Email check failed (attempt {attempt + 1}/{max_retries}): {e}"
            log_error(error_msg, critical=(is_last and not transient), config=config)
            if is_last and not transient:
                try:
                    from modules.toast import queue_toast
                    queue_toast("Email check failed. Check credentials.")
                except Exception:
                    pass
            time.sleep(5)


def _process_email(msg, config, screens):
    """Handle one email end-to-end: bounce/approval/opt-out/opt-in/unapproved, or
    save its photos and send one confirmation with thumbnails."""
    sender = msg.get("from", "")
    subject = msg.get("subject", "")

    # Ignore bounce / delivery-failure notices (they carry Gmail icon "photos").
    if _is_bounce(sender, subject, msg):
        return
    if _is_approval_reply(subject, msg, config):
        return
    if _is_optout(subject, msg):
        addr = _extract_email(sender)
        if addr:
            add_nudge_optout(addr)
            _send_optout_confirmation(addr, config)
            print(f"[Selah] {addr} opted out of reminders")
        return
    if _is_optin(subject, msg):
        addr = _extract_email(sender)
        if addr and addr.lower() in load_nudge_optout():
            remove_nudge_optout(addr)
            _send_optin_confirmation(addr, config)
            print(f"[Selah] {addr} re-subscribed to reminders")
        return

    approved_senders = load_approved_senders()
    if approved_senders and not any(s in sender for s in approved_senders):
        _handle_unapproved_sender(sender, msg, config, screens)
        return

    subject_date = parse_subject_date(subject)   # a greeting date, or None
    date = subject_date or get_email_date(msg)

    # The subject line is the caption; the body is a fallback when it's empty.
    caption = _subject_caption(subject)
    if not caption:
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    caption = extract_caption(
                        part.get_payload(decode=True).decode(errors="replace"))
                except Exception:
                    pass
                break

    # Photos are detected by content-type (catches inline + HEIC).
    saved_paths = []     # newly written this pass
    reply_photos = []    # every photo in the email (new OR already saved)
    had_media = False
    final_date = date
    for filename, data in iter_media_parts(msg):
        had_media = True
        file_path, is_new = save_media_bytes(data, filename, config, sender)
        if not file_path:
            continue
        # file_path is the correct on-disk copy of THIS photo (new or existing),
        # so the reply always thumbnails the right image.
        reply_photos.append(file_path)
        if subject_date:                        # (re-)schedule a dated greeting
            try:
                from modules.scheduled_media import add_scheduled
                add_scheduled(file_path, subject_date.strftime("%m-%d"),
                              caption=caption, recurring=not _subject_has_year(subject),
                              target_iso=subject_date.isoformat())
            except Exception as e:
                log_error(f"Greeting schedule failed: {e}")
        if not is_new:                          # already on disk — nothing more to do
            continue
        saved_paths.append(file_path)
        final_date = date or get_file_date(file_path)
        queue_media(file_path, final_date, caption, config)
        try:
            from modules.leaderboard import update_leaderboard
            update_leaderboard(sender, 1)
        except Exception:
            pass
        try:
            from modules.cloud_backup import backup_to_drive
            if config.get("cloud_backup_enabled", False):
                backup_to_drive(file_path, config)
        except Exception:
            pass
        try:
            from modules.pending_photos import add as _queue_new
            _queue_new(file_path)   # surface at the next rotation
        except Exception:
            pass
        try:
            from modules.new_photo_hint import note_new_photo
            note_new_photo(kind="email")
        except Exception:
            pass
        log_media(file_path, sender, final_date, caption)

    # Acknowledge EVERY email that contained a photo — even ones already on disk.
    # Pass the greeting date (None for an immediate submission) so the reply reads
    # correctly; a no-year date recurs every year.
    if had_media:
        recurring = bool(subject_date) and not _subject_has_year(subject)
        send_auto_reply(sender, config, subject_date, reply_photos, caption,
                        recurring=recurring)


def parse_subject_date(subject):
    """Extract date from email subject line.
    Handles: 'Happy Birthday Mom May 10', 'Anniversary Oct 15', '2025-03-01'
    """
    if not subject:
        return None
    # Try ISO date first: 2025-03-01
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    if iso_match:
        try:
            return datetime.datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    # Try month+day: 'May 10', 'Oct 15', 'Sept 4', 'Sept. 4', 'January 1'.
    # Match a 3-letter month stem + any remaining letters (so Sep/Sept/September
    # all work) + optional '.', then map the stem straight to a month number
    # (avoids strptime's locale abbreviations, where 'Sept' is invalid).
    _MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    month_day = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
        subject, re.I)
    if month_day:
        try:
            m = _MONTHS[month_day.group(1).lower()]
            day = int(month_day.group(2))
            year = datetime.datetime.now().year
            d = datetime.date(year, m, day)
            # No year given -> use the next occurrence, not a past one.
            if d < datetime.date.today() and not _subject_has_year(subject):
                d = datetime.date(year + 1, m, day)
            return d
        except Exception:
            pass
    # Relative: "2nd Sunday of May", "last Monday of October" (Mother's Day etc.)
    rel = re.search(
        r"(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+"
        r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+of\s+"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*",
        subject, re.I)
    if rel:
        try:
            return _nth_weekday_of_month(rel.group(1), rel.group(2), rel.group(3),
                                         datetime.datetime.now().year)
        except Exception:
            pass
    return None


def _nth_weekday_of_month(ordinal, weekday, month, year):
    """Date of the Nth given weekday in a month, e.g. 2nd Sunday of May."""
    import calendar
    ords = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1}
    wdays = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    n = ords[ordinal.lower()]
    wd = wdays[weekday.lower()[:3]]
    mo = months[month.lower()[:3]]
    days = [d for d in range(1, calendar.monthrange(year, mo)[1] + 1)
            if datetime.date(year, mo, d).weekday() == wd]
    if not days:
        return None
    return datetime.date(year, mo, days[-1] if n == -1 else days[n - 1])


def _subject_has_year(subject):
    """True if the subject names a specific 4-digit year (=> one-time greeting)."""
    return bool(re.search(r"\b(?:19|20)\d{2}\b", subject or ""))


def _subject_caption(subject):
    """The subject line cleaned for use as the caption: drop Re:/Fwd: and the
    trailing date phrase (that's for scheduling, not the caption)."""
    s = re.sub(r"^\s*(re|fwd|fw)\s*:\s*", "", subject or "", flags=re.I).strip()
    # Strip a trailing date: ISO, "2nd Sunday of May", or "Aug 9".
    patterns = [
        r"\s*\d{4}-\d{2}-\d{2}\s*$",
        r"\s*(?:1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+"
        r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+of\s+"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*$",
        r"\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
        r"\s+\d{1,2}(?:st|nd|rd|th)?\s*$",
    ]
    for pat in patterns:
        stripped = re.sub(pat, "", s, flags=re.I)
        if stripped != s:
            s = stripped
            break
    s = s.rstrip(" ,-–—:").strip()
    return s or re.sub(r"^\s*(re|fwd|fw)\s*:\s*", "", subject or "", flags=re.I).strip()


def get_email_date(msg):
    """Get sent date from email headers."""
    try:
        date_str = msg.get("Date")
        if date_str:
            return parsedate_to_datetime(date_str).date()
    except Exception as e:
        log_error(f"Failed to parse email date: {e}", critical=False)
    return None


def get_file_date(file_path):
    """Get file creation date as fallback."""
    try:
        ctime = os.path.getctime(file_path)
        return datetime.datetime.fromtimestamp(ctime).date()
    except Exception:
        return datetime.datetime.now().date()


def extract_caption(body):
    """Extract caption from email body.
    Looks for 'Caption: ...' line first, then falls back to first sentence.
    """
    try:
        # Check for explicit Caption: line
        caption_match = re.search(r"Caption:\s*(.+)", body, re.I)
        if caption_match:
            return caption_match.group(1).strip()
        # Fallback: first non-empty sentence
        sentences = re.split(r'[.!?\n]+', body)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(sentence) > 2:
                return sentence
        return ""
    except Exception:
        return ""


def _is_bounce(sender, subject, msg):
    """True for delivery-failure / auto-generated system mail (mailer-daemon,
    postmaster, DSN reports) — never a real photo submission."""
    s = (sender or "").lower()
    if "mailer-daemon" in s or "postmaster@" in s or "mail delivery subsystem" in s:
        return True
    subj = (subject or "").lower()
    if any(k in subj for k in ("delivery status notification", "undelivered mail",
                               "delivery incomplete", "failure notice",
                               "returned mail", "mail delivery failed",
                               "undeliverable")):
        return True
    try:
        ctype = (msg.get_content_type() or "").lower()
        if ctype in ("multipart/report",) or msg.get("auto-submitted", "").lower().startswith("auto"):
            return True
    except Exception:
        pass
    return False


def _sender_folder(sender):
    """A filesystem-safe folder name for a sender, spaces removed and each word
    capitalised: 'Laura Sommer' -> 'LauraSommer', 'evan.e.sommer' -> 'EvanESommer'."""
    name, addr = parseaddr(sender or "")
    label = (name or "").strip()
    if not label and addr:
        label = re.sub(r"[._]+", " ", addr.split("@")[0])
    parts = re.findall(r"[A-Za-z0-9]+", label)
    folder = "".join(p[:1].upper() + p[1:] for p in parts)
    return folder or "unknown"


_IMG_MIME_EXT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/heic": ".heic", "image/heif": ".heif", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp",
}
_VID_MIME_EXT = {
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi",
}


def iter_media_parts(msg, min_image_bytes=15000):
    """Yield (filename, bytes) for photo/video parts, detected by content-type
    so inline images and HEIC files are caught (not just 'attachment' parts).
    Tiny images (email-signature logos, tracking pixels) are skipped."""
    idx = 0
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "").lower()
        ext = _IMG_MIME_EXT.get(ctype) or _VID_MIME_EXT.get(ctype)
        if not ext:
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            data = None
        if not data:
            continue
        if ctype in _IMG_MIME_EXT and len(data) < min_image_bytes:
            continue  # skip signature logos / pixels
        fn = part.get_filename()
        if not fn or not fn.lower().endswith(tuple(list(_IMG_MIME_EXT.values()) +
                                                   list(_VID_MIME_EXT.values()))):
            idx += 1
            fn = f"photo_{idx}{ext}"
        yield fn, data


def _same_bytes(path, data):
    """True if `path` already holds exactly these bytes (a real duplicate)."""
    try:
        if path.stat().st_size != len(data):
            return False
        return path.read_bytes() == data
    except Exception:
        return False


def save_media_bytes(data, filename, config, sender=None):
    """Write photo/video bytes under media/email/<sender>/.

    Dedups by CONTENT, not filename: generic names like 'photo_1.jpg' collide
    across different submissions, so a name clash alone must NOT drop a new photo.
    Returns (path, is_new): `path` is the on-disk file that holds these exact
    bytes — a fresh save (is_new=True) or the EXISTING duplicate (is_new=False,
    the real matching path, which may be a '<name>_N' suffix). (None, False) on
    error. Returning the true matching path is what keeps a re-send's reply
    thumbnail correct."""
    try:
        folder = Path(config.get("email_dir", "media/email")) / _sender_folder(sender)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / filename
        if dest.exists():
            if _same_bytes(dest, data):
                return str(dest), False       # identical content — real duplicate
            # Same name, different photo — find a free unique name (and return the
            # matching path if the identical content already sits under a suffix).
            base, ext = os.path.splitext(filename)
            i = 1
            while True:
                cand = folder / f"{base}_{i}{ext}"
                if not cand.exists():
                    dest = cand
                    break
                if _same_bytes(cand, data):
                    return str(cand), False
                i += 1
        with open(dest, "wb") as f:
            f.write(data)
        return str(dest), True
    except Exception as e:
        log_error(f"Failed to save media: {e}", critical=False, config=config)
        return None, False


def save_attachment(part, config, sender=None):
    """Save an email attachment under media/email/<sender>/ (folders by sender)."""
    try:
        filename = part.get_filename()
        if not filename:
            return None
        folder = Path(config.get("email_dir", "media/email")) / _sender_folder(sender)
        folder.mkdir(parents=True, exist_ok=True)

        file_path = folder / filename
        # Avoid overwriting existing files
        counter = 1
        while file_path.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            file_path = folder / f"{stem}_{counter}{suffix}"
            counter += 1

        with open(file_path, "wb") as f:
            f.write(part.get_payload(decode=True))
        return str(file_path)
    except Exception as e:
        log_error(f"Failed to save attachment: {e}", critical=True, config=config)
        return None


def queue_media(file_path, date, caption, config):
    """Queue media for display (logging/scheduling)."""
    try:
        if not date and config.get("immediate_display", False):
            print(f"[Selah] Immediately displaying: {file_path}")
        else:
            print(f"[Selah] Queued: {file_path} for {date} with caption: {caption}")
    except Exception as e:
        log_error(f"Failed to queue media: {e}", critical=False)


DID_YOU_KNOW = """
— Did you know? —
• There's a leaderboard! The more photos you send, the higher you climb.
• Your SUBJECT line becomes the caption shown under your photo — so make it a good one.
• Put a date in the subject and we'll re-show your photo on that day, every hour:
      Happy Birthday, Liam Aug 9              (recurs EVERY year)
      Happy Mother's Day, 2nd Sunday of May   (recurs EVERY year)
      Merry Christmas 2026-12-25              (that year ONLY — it has a year)
  No year = every year; add a year for a one-time show.

Keep them coming — we love seeing your photos up on the display!
- The Selah Family Display
"""

_DYK_HTML = """
<div style="margin-top:22px;padding:16px 18px;background:#f4f1ea;border-radius:12px;
            border:1px solid #e6e0d4;font-size:14px;color:#4a4a4a;line-height:1.55">
  <div style="font-weight:700;color:#b5651d;margin-bottom:8px">Did you know?</div>
  <ul style="margin:0;padding-left:18px">
    <li>There's a <b>leaderboard</b> — the more photos you send, the higher you climb.</li>
    <li>Your <b>subject line</b> becomes the caption shown under your photo.</li>
    <li>Put a date in the subject and we'll re-show it on that day, <b>every hour</b>:
      <div style="margin:6px 0 0;font-family:monospace;font-size:13px;color:#555">
        Happy Birthday, Liam Aug 9 &nbsp;<span style="color:#999">(every year)</span><br>
        Merry Christmas 2026-12-25 &nbsp;<span style="color:#999">(that year only)</span>
      </div>
      <div style="margin-top:4px;color:#777">No year = every year; add a year for a one-time show.</div>
    </li>
  </ul>
</div>
"""


def _base_reply(date, count=1):
    """Plain 'what happens next' line, pluralised for the number of photos."""
    word = "photo" if count == 1 else f"{count} photos"
    verb = "is" if count == 1 else "are"
    if date:
        return (f"Thank you! Your {word} {verb} saved and will appear on {date} — "
                "shown that day every hour, in turn with everyone else's greetings "
                "and that day's memories.")
    return (f"Thank you! Your {word} will appear on the display shortly, and again "
            "from time to time as the slideshow cycles.")


def get_custom_response(sender, date, config, count=1):
    """Get the confirmation body (custom template, else the plural base line)."""
    try:
        if not config.get("custom_email_responses", False):
            return _base_reply(date, count)
        try:
            with open("email_responses.json", "r") as f:
                responses = json.load(f)
        except FileNotFoundError:
            return _base_reply(date, count)

        for response in responses:
            condition = response.get("condition", "")
            msg_template = response.get("message", "Thank you!")
            if condition == "immediate" and not date:
                return msg_template
            if condition == "scheduled" and date:
                return msg_template.replace("{date}", str(date))
            if condition.startswith("sender:") and condition.split(":")[1] in sender:
                return msg_template
            if condition == "default":
                return msg_template.replace("{date}", str(date or "immediate display"))
        return _base_reply(date, count)
    except Exception:
        return _base_reply(date, count)


def _thumbnail_bytes(path, size=170):
    """A small JPEG thumbnail of a photo (upright), or None for videos/failures."""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
            return buf.getvalue()
    except Exception:
        return None


def _submit_guidance(config):
    """(plain, html) guidance: keep emails small, use the shared Drive folder for
    big batches/videos. The folder link only appears when submit_drive_url is set."""
    url = (config.get("submit_drive_url") or "").strip()
    plain = ("\nA few photos per email is perfect — very large emails (lots of "
             "photos at once, or roughly 25 MB+) can bounce, so please keep each "
             "one to a handful.")
    link_html = ""
    if url:
        plain += ("\nHave a big batch, high-res originals, or a video? Drop them "
                  f"straight into our shared folder:\n  {url}")
        link_html = (
            f'<div style="margin-top:10px"><a href="{url}" '
            'style="color:#b5651d;font-weight:600;text-decoration:none">'
            '📁 Open the shared photo folder →</a>'
            '<div style="font-size:12px;color:#999;margin-top:2px">'
            'best for big batches, videos, or high-res originals</div></div>')
    html = ('<div style="margin-top:18px;padding:14px 16px;background:#fbf3e9;'
            'border:1px solid #eddcc7;border-radius:12px;font-size:13.5px;'
            'color:#5a5045;line-height:1.5"><b>A few at a time is perfect</b> — '
            'very large emails can bounce, so please keep each one to a handful '
            'of photos.' + link_html + '</div>')
    return plain, html


def _when_phrase(date, recurring):
    """How to phrase the display date in the reply: 'September 4 (every year)' for
    a recurring greeting, 'December 25, 2026' for a one-time one, or None."""
    if not date:
        return None
    try:
        d = date if hasattr(date, "strftime") else datetime.date.fromisoformat(str(date)[:10])
    except Exception:
        return str(date)
    return d.strftime("%B %-d") + " (every year)" if recurring else d.strftime("%B %-d, %Y")


def send_auto_reply(sender, config, date, photos=None, caption=None, recurring=False):
    """Send a formatted confirmation, plural-aware, with thumbnails of the
    submitted photos inline (the caption shown under each). `date` is the greeting
    date (None for an immediate submission); `recurring` phrases a yearly greeting."""
    if not config.get("email_address") or not config.get("email_password"):
        return
    photos = photos or []
    count = len(photos) or 1
    owner = config["email_address"]
    try:
        # Feed a recurring-aware date string to the templates so a no-year greeting
        # reads 'every year', and a non-dated submission reads 'immediate'.
        when = _when_phrase(date, recurring)
        body = get_custom_response(sender, when, config, count)
        guide_plain, guide_html = _submit_guidance(config)

        # Build inline thumbnails (skip videos / unreadable).
        thumbs = []
        for p in photos:
            data = _thumbnail_bytes(p)
            if data:
                thumbs.append(data)

        root = MIMEMultipart("related")
        root["Subject"] = "Selah Submission Received"
        root["From"] = owner
        root["To"] = sender

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body + "\n" + guide_plain + "\n" + DID_YOU_KNOW, "plain"))

        thumb_html = ""
        if thumbs:
            import html as _html
            cap = _html.escape((caption or "").strip())
            cap_html = (f'<div style="font-size:12.5px;color:#777;margin-top:6px;'
                        f'max-width:150px">{cap}</div>' if cap else "")
            cells = "".join(
                '<div style="display:inline-block;text-align:center;margin:5px;'
                'vertical-align:top">'
                f'<img src="cid:thumb{i}" width="150" '
                'style="border-radius:10px;border:4px solid #fff;'
                'box-shadow:0 2px 6px rgba(0,0,0,.25)">'
                f'{cap_html}</div>'
                for i in range(len(thumbs)))
            thumb_html = f'<div style="margin:18px 0;text-align:center">{cells}</div>'

        html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:560px;margin:0 auto;color:#333">
  <div style="background:linear-gradient(135deg,#b5651d,#d98b3f);color:#fff;
              padding:20px 22px;border-radius:14px 14px 0 0">
    <div style="font-size:22px;font-weight:700">📷 Got it — thank you!</div>
    <div style="opacity:.9;font-size:14px;margin-top:2px">The Selah Family Display</div>
  </div>
  <div style="padding:20px 22px;background:#fff;border:1px solid #eee;border-top:0;
              border-radius:0 0 14px 14px">
    <p style="font-size:15px;line-height:1.6;margin:0">{body}</p>
    {thumb_html}
    {guide_html}
    {_DYK_HTML}
  </div>
</div>"""
        alt.attach(MIMEText(html, "html"))
        root.attach(alt)

        for i, data in enumerate(thumbs):
            img = MIMEImage(data, "jpeg")
            img.add_header("Content-ID", f"<thumb{i}>")
            img.add_header("Content-Disposition", "inline", filename=f"thumb{i}.jpg")
            root.attach(img)

        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(owner, config["email_password"])
            server.send_message(root)
    except Exception as e:
        log_error(f"Failed to send auto-reply: {e}", critical=False, config=config)


def load_approved_senders(path="approved_senders.json"):
    """Load approved senders list."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []  # Empty list means allow all senders


PENDING_FILE = "pending_approvals.json"
INVITE_LOG_FILE = "invite_log.json"

ANNUAL_INVITE_SUBJECT = "Send your favourite photos to the family display!"

ANNUAL_INVITE_BODY = """\
Hi {name}!

This is a friendly reminder that you can share photos and videos with the \
family display anytime by emailing them to:

    {email}

Here's how it works:

  - Just attach a photo (JPG, PNG) or video (MP4, MOV) and send!
  - Your photo will appear on the family display right away.

  - Want to add a caption? The first sentence of your email becomes the \
caption shown under the photo.

A NOTE ON BIG BATCHES:
A few photos per email is best — very large emails (lots of photos at once, or
roughly 25 MB+) can bounce. For bigger batches, high-res originals, or videos,
upload straight to our shared family Google Drive folder:
{drive}
Dated filenames work there too, e.g. name a photo "Happy Birthday, Mom Sept 4.jpg".

SENDING A BIRTHDAY (OR ANNIVERSARY) GREETING — plan ahead!
You don't have to remember on the day. Email your photo a few days early
(say 3 days before) and put the person's name and date in the subject line:

      Subject: Happy Birthday, Mom Sept 4

Your greeting is saved and shown FIRST THING on the morning of Sept 4 —
together with everyone else's greetings for that day, and favourite photos
that feature the birthday person. Other date formats work too:

      Subject: Merry Christmas 2026-12-25
      Subject: Happy Anniversary, Mom & Dad June 15

We'd love to see your photos up on the screen — a few at a time by email, or a
whole batch in the shared folder!

- The Selah Family Display
"""


def _invite_drive_text(config):
    """The shared-folder line for the invite: the real link if set, else a
    reply-for-link fallback."""
    url = (config.get("submit_drive_url") or "").strip()
    return f"    {url}" if url else "    (Reply to this email and we'll send you the folder link.)"


def _handle_unapproved_sender(sender, msg, config, screens):
    """Save attachments to pending folder and email owner for approval."""
    subject = msg.get("subject", "")

    # Extract sender email address
    sender_email = _extract_email(sender)
    sender_name = sender.split("<")[0].strip().strip('"').strip("'") or sender_email

    # Save any attachments to a pending folder
    pending_files = []
    valid_exts = tuple(config.get("valid_extensions", []))
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename()
            if filename and filename.lower().endswith(valid_exts):
                pending_dir = Path(config.get("media_folder", "media")) / "pending"
                pending_dir.mkdir(parents=True, exist_ok=True)
                file_path = pending_dir / filename
                counter = 1
                while file_path.exists():
                    stem = Path(filename).stem
                    suffix = Path(filename).suffix
                    file_path = pending_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                with open(file_path, "wb") as f:
                    f.write(part.get_payload(decode=True))
                pending_files.append(str(file_path))

    # Record the pending approval
    pending = _load_pending()
    pending_entry = {
        "sender": sender,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "subject": subject,
        "files": pending_files,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    pending.append(pending_entry)
    _save_pending(pending)

    # Send approval request to the owner
    attachment_info = f"{len(pending_files)} file(s)" if pending_files else "no attachments"
    _send_approval_request(sender_name, sender_email, subject, attachment_info, config)

    # No on-screen takeover — a subtle corner badge (drawn from main.py) shows
    # the pending count, and F5 approves them all.
    print(f"[Selah] Pending approval for {sender_email} ({attachment_info})")


def _send_approval_request(sender_name, sender_email, subject, attachment_info, config):
    """Email the owner asking to approve a new sender."""
    try:
        owner = config.get("email_address", "")
        body = (
            f"New submission from an unapproved sender:\n\n"
            f"  Name: {sender_name}\n"
            f"  Email: {sender_email}\n"
            f"  Subject: {subject}\n"
            f"  Attachments: {attachment_info}\n\n"
            f"To approve this sender and add their photos to the slideshow, "
            f"reply to this email with just the word: yes\n\n"
            f"To ignore, simply don't reply."
        )
        msg = MIMEText(body)
        msg["Subject"] = f"[Selah Approval] {sender_name} ({sender_email})"
        msg["From"] = owner
        msg["To"] = owner

        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(owner, config["email_password"])
            server.send_message(msg)
    except Exception as e:
        log_error(f"Failed to send approval request: {e}", config=config)


def _is_approval_reply(subject, msg, config):
    """Check if this email is a 'yes' reply to an approval request.
    If so, approve the sender, move their pending files, and return True.
    """
    if "[Selah Approval]" not in (subject or ""):
        return False

    # Check that this is from the owner replying to themselves
    sender = msg.get("from", "")
    owner = config.get("email_address", "")
    if owner not in sender:
        return False

    # Check the body for "yes"
    body_text = ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                body_text = part.get_payload(decode=True).decode(errors="replace")
            except Exception:
                pass
            break

    # Look for "yes" as the first word in the reply
    first_line = body_text.strip().split("\n")[0].strip().lower() if body_text else ""
    if not first_line.startswith("yes"):
        return False

    # Extract the sender email from the subject line
    email_match = re.search(r"\(([^)]+@[^)]+)\)", subject)
    if not email_match:
        return False
    approved_email = email_match.group(1).strip()

    # Add to approved senders
    senders = load_approved_senders()
    if approved_email not in senders:
        senders.append(approved_email)
        _save_approved_senders(senders)

    # Move pending files to display folder and process them
    pending = _load_pending()
    remaining = []
    for entry in pending:
        if entry.get("sender_email") == approved_email:
            for file_path in entry.get("files", []):
                if os.path.isfile(file_path):
                    _move_pending_to_display(file_path, config)
        else:
            remaining.append(entry)
    _save_pending(remaining)

    # Notify the approved sender
    try:
        reply_msg = MIMEText(
            f"Great news! Your photos have been approved for the Selah display. "
            f"Future submissions from {approved_email} will be added automatically."
        )
        reply_msg["Subject"] = "Selah - You've been approved!"
        reply_msg["From"] = config["email_address"]
        reply_msg["To"] = approved_email

        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["email_address"], config["email_password"])
            server.send_message(reply_msg)
    except Exception as e:
        log_error(f"Failed to send approval notification: {e}")

    # Toast
    try:
        from modules.toast import queue_toast
        queue_toast(f"Approved: {approved_email}")
    except Exception:
        pass

    print(f"[Selah] Approved sender: {approved_email}")
    return True


def _move_pending_to_display(file_path, config):
    """Move a file from the pending folder to the display folder."""
    try:
        import shutil
        dest_dir = Path(config.get("display_dir", "media/display"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = dest_dir / filename
        counter = 1
        while dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        shutil.move(file_path, str(dest))
        print(f"[Selah] Moved approved file: {filename} -> {dest}")
    except Exception as e:
        log_error(f"Failed to move pending file {file_path}: {e}")


def _extract_email(sender_str):
    """Extract email address from a 'Name <email>' string."""
    match = re.search(r"<([^>]+)>", sender_str)
    if match:
        return match.group(1).strip()
    # Maybe it's just a bare email
    if "@" in sender_str:
        return sender_str.strip()
    return sender_str


def _save_approved_senders(senders, path="approved_senders.json"):
    """Save the approved senders list."""
    try:
        with open(path, "w") as f:
            json.dump(senders, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save approved senders: {e}")


def _load_pending():
    """Load pending approvals list."""
    try:
        with open(PENDING_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_pending(pending):
    """Save pending approvals list."""
    try:
        with open(PENDING_FILE, "w") as f:
            json.dump(pending, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save pending approvals: {e}")


def count_pending():
    """How many senders are awaiting approval."""
    return len(_load_pending())


def approve_all_pending(config):
    """Approve every pending sender at once: whitelist them, move their photos
    into the display folder, and clear the queue. Returns the count approved.
    """
    pending = _load_pending()
    if not pending:
        return 0
    from pathlib import Path
    senders = load_approved_senders()
    display_dir = Path(config.get("display_dir", "media/display"))
    display_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for entry in pending:
        em = (entry.get("sender_email") or "").strip()
        if em and em not in senders:
            senders.append(em)
        for fp in entry.get("files", []):
            try:
                p = Path(fp)
                if p.exists():
                    dest = display_dir / p.name
                    n = 1
                    while dest.exists():
                        dest = display_dir / f"{p.stem}_{n}{p.suffix}"
                        n += 1
                    p.rename(dest)
                    moved += 1
            except Exception as e:
                log_error(f"Failed to move pending file {fp}: {e}")

    _save_approved_senders(senders)
    _save_pending([])
    print(f"[Selah] Approved all pending: {len(pending)} sender(s), {moved} file(s)")
    return len(pending)


def send_annual_invites(config):
    """Send an annual invite to all approved senders reminding them to submit photos.

    Checks invite_log.json to ensure each sender only gets one invite per year.
    Call this from the main loop — it will only send when due (once per year, in January).
    """
    now = datetime.datetime.now()

    # Only send invites in January
    if now.month != 1:
        return

    invite_log = _load_invite_log()
    current_year = str(now.year)

    # If we've already done this year's invites, skip
    if invite_log.get("last_year") == current_year:
        return

    # Only send on the first week of January
    if now.day > 7:
        return

    senders = load_approved_senders()
    if not senders:
        return

    owner = config.get("email_address", "")
    if not owner or not config.get("email_password"):
        return

    optout = load_nudge_optout()
    sent_count = 0
    for sender_email in senders:
        # Skip the system's own email and anyone who opted out.
        if sender_email == owner or sender_email.lower() in optout:
            continue

        # Derive a friendly name from the email
        name = sender_email.split("@")[0].replace(".", " ").replace("_", " ").title()

        try:
            body = (ANNUAL_INVITE_BODY.replace("{name}", name).replace("{email}", owner)
                        .replace("{drive}", _invite_drive_text(config)))
            msg = MIMEText(body)
            msg["Subject"] = ANNUAL_INVITE_SUBJECT
            msg["From"] = owner
            msg["To"] = sender_email

            with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
                server.starttls()
                server.login(owner, config["email_password"])
                server.send_message(msg)

            sent_count += 1
            print(f"[Selah] Sent annual invite to {sender_email}")
        except Exception as e:
            log_error(f"Failed to send invite to {sender_email}: {e}")

    # Mark this year as done
    invite_log["last_year"] = current_year
    invite_log["last_sent"] = now.isoformat()
    invite_log["count"] = sent_count
    _save_invite_log(invite_log)

    print(f"[Selah] Sent {sent_count} annual invites for {current_year}")


NUDGE_LOG_FILE = "nudge_log.json"
NUDGE_OPTOUT_FILE = "nudge_optout.json"

NUDGE_SUBJECT = "{name}, we'd love a new photo on the display"


def load_nudge_optout():
    """Set of lowercased emails that have opted out of reminders."""
    try:
        with open(NUDGE_OPTOUT_FILE) as f:
            return {str(e).lower() for e in json.load(f)}
    except Exception:
        return set()


def add_nudge_optout(email):
    """Record an opt-out so we never nudge/invite this address again."""
    addr = (email or "").lower().strip()
    if not addr:
        return
    out = load_nudge_optout()
    if addr in out:
        return
    out.add(addr)
    try:
        with open(NUDGE_OPTOUT_FILE, "w") as f:
            json.dump(sorted(out), f, indent=2)
    except Exception as e:
        log_error(f"Failed to save nudge opt-out: {e}")


def remove_nudge_optout(email):
    """Re-subscribe an address (remove it from the opt-out list)."""
    addr = (email or "").lower().strip()
    out = load_nudge_optout()
    if addr not in out:
        return
    out.discard(addr)
    try:
        with open(NUDGE_OPTOUT_FILE, "w") as f:
            json.dump(sorted(out), f, indent=2)
    except Exception as e:
        log_error(f"Failed to update nudge opt-out: {e}")


def _send_simple_email(to_email, subject, body, config):
    """Send a plain-text email from the display account. Best-effort."""
    owner = config.get("email_address", "")
    if not owner or not config.get("email_password") or not to_email:
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = owner
        msg["To"] = to_email
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(owner, config["email_password"])
            server.send_message(msg)
    except Exception as e:
        log_error(f"Failed to send email to {to_email}: {e}")


def _send_optout_confirmation(to_email, config):
    name = to_email.split("@")[0].replace(".", " ").replace("_", " ").title()
    owner_name = config.get("display_owner_name", "the family display")
    body = (f"Hi {name},\n\n"
            f"You're unsubscribed — no more reminders from {owner_name}.\n\n"
            f"You can still share photos anytime: just email them to "
            f"{config.get('email_address','')}. And if you'd like reminders "
            f"again, reply with \"start\".\n\n- The Selah Family Display\n")
    _send_simple_email(to_email, "You're unsubscribed", body, config)


def _send_optin_confirmation(to_email, config):
    name = to_email.split("@")[0].replace(".", " ").replace("_", " ").title()
    owner_name = config.get("display_owner_name", "the family display")
    body = (f"Hi {name},\n\n"
            f"You're back on the list — we'll send the occasional reminder to "
            f"share a photo with {owner_name}. Reply \"stop\" anytime to opt "
            f"out again.\n\n- The Selah Family Display\n")
    _send_simple_email(to_email, "You're subscribed", body, config)


def _is_optin(subject, msg):
    """True if an incoming email asks to re-subscribe (no attachment + start)."""
    text = (subject or "").lower()
    try:
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                return False
            if part.get_content_type() == "text/plain":
                try:
                    text += " " + part.get_payload(decode=True).decode(errors="replace").lower()
                except Exception:
                    pass
    except Exception:
        pass
    return text.strip() in ("start", "start.", "resubscribe", "subscribe")


def _is_optout(subject, msg):
    """True if an incoming email is an opt-out request (no attachment + a
    stop/unsubscribe phrase)."""
    text = (subject or "").lower()
    has_attach = False
    try:
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                has_attach = True
            if part.get_content_type() == "text/plain":
                try:
                    text += " " + part.get_payload(decode=True).decode(errors="replace").lower()
                except Exception:
                    pass
    except Exception:
        pass
    if has_attach:
        return False  # it's a photo submission, not an opt-out
    keys = ("unsubscribe", "opt out", "opt-out", "no more reminder",
            "stop reminder", "stop sending", "remove me")
    if any(k in text for k in keys):
        return True
    return text.strip() in ("stop", "stop.")

NUDGE_BODY = """\
Hi {name},

It's been a while since your last photo lit up {owner}. Share a favourite \
memory — just reply to this email with a photo attached, and it'll appear on \
the display.

(Prefer not to get these reminders? Just reply with "stop" and we'll \
take you off the list.)

- The Selah Family Display
"""


def _nudge_html(name, owner_name, has_thumb, caption):
    """Branded HTML nudge, optionally featuring the recipient's own last photo."""
    thumb_block = ""
    if has_thumb:
        cap = ""
        if caption:
            cap = (f'<div style="font-size:13px;color:#888;margin-top:8px;'
                   f'font-style:italic">"{caption}"</div>')
        thumb_block = f"""
    <div style="margin:20px 0;text-align:center">
      <div style="font-size:13px;color:#999;margin-bottom:8px">
        Remember this one you sent?</div>
      <img src="cid:lastphoto" width="230"
           style="border-radius:12px;border:5px solid #fff;
                  box-shadow:0 3px 10px rgba(0,0,0,.25)">
      {cap}
    </div>"""
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:560px;margin:0 auto;color:#333">
  <div style="background:linear-gradient(135deg,#b5651d,#d98b3f);color:#fff;
              padding:20px 22px;border-radius:14px 14px 0 0">
    <div style="font-size:22px;font-weight:700">📷 We miss your photos, {name}!</div>
    <div style="opacity:.9;font-size:14px;margin-top:2px">{owner_name}</div>
  </div>
  <div style="padding:20px 22px;background:#fff;border:1px solid #eee;border-top:0;
              border-radius:0 0 14px 14px">
    <p style="font-size:15px;line-height:1.6;margin:0">
      It's been a while since one of your photos lit up the display. Share a
      favourite memory and it'll be up within a minute.</p>
    {thumb_block}
    <div style="text-align:center;margin:22px 0 6px">
      <div style="display:inline-block;background:#b5651d;color:#fff;font-weight:600;
                  padding:12px 22px;border-radius:999px;font-size:15px">
        Just reply to this email with a photo attached 📎</div>
    </div>
    {_DYK_HTML}
    <p style="font-size:12px;color:#aaa;margin:18px 0 0;text-align:center">
      Prefer not to get these? Reply "stop" and we'll take you off the list.</p>
  </div>
</div>"""


def _last_submission_by_email():
    """Map sender email -> most recent submission datetime, from media_log."""
    out = {}
    try:
        with open("media_log.json") as f:
            log = json.load(f)
    except Exception:
        return out
    for e in log:
        addr = _extract_email(e.get("sender", "") or "")
        ts = e.get("timestamp")
        if not addr or not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except Exception:
            continue
        if addr not in out or dt > out[addr]:
            out[addr] = dt
    return out


def _last_photo_by_email():
    """Map sender email -> (path, caption) of their most recent logged photo."""
    latest = {}   # addr -> (dt, path, caption)
    try:
        with open("media_log.json") as f:
            log = json.load(f)
    except Exception:
        return {}
    for e in log:
        addr = _extract_email(e.get("sender", "") or "")
        ts, path = e.get("timestamp"), e.get("file_path")
        if not addr or not ts or not path:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except Exception:
            continue
        if addr not in latest or dt > latest[addr][0]:
            latest[addr] = (dt, path, e.get("caption") or "")
    return {a: (p, c) for a, (d, p, c) in latest.items()}


def send_inactivity_nudges(config):
    """Gently nudge approved senders who haven't sent a photo in a while.

    Personalized, one-line CTA, throttled to once per nudge_inactive_weeks per
    person (and at most one scan per day). Call from the main loop — it only
    sends when due.
    """
    if not config.get("nudge_enabled", True):
        return
    owner = config.get("email_address", "")
    if not owner or not config.get("email_password"):
        return
    senders = load_approved_senders()
    if not senders:
        return

    now = datetime.datetime.now()
    weeks = int(config.get("nudge_inactive_weeks", 4))
    gap = datetime.timedelta(weeks=max(1, weeks))

    try:
        with open(NUDGE_LOG_FILE) as f:
            nlog = json.load(f)
    except Exception:
        nlog = {}
    if nlog.get("_last_run", "")[:10] == now.date().isoformat():
        return  # already scanned today

    owner_name = config.get("display_owner_name", "the family display")
    last_sub = _last_submission_by_email()
    last_photo = _last_photo_by_email()
    optout = load_nudge_optout()
    sent = 0
    for sender_email in senders:
        if sender_email == owner or sender_email.lower() in optout:
            continue
        ls = last_sub.get(sender_email)
        if ls is not None and (now - ls) < gap:
            continue  # they've contributed recently — no nudge
        last_nudge = nlog.get(sender_email)
        if last_nudge:
            try:
                if (now - datetime.datetime.fromisoformat(last_nudge)) < gap:
                    continue  # nudged recently
            except Exception:
                pass
        name = sender_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        try:
            # A thumbnail of the recipient's own most recent photo, if we have one.
            path, caption = last_photo.get(sender_email, (None, ""))
            thumb = _thumbnail_bytes(path, size=230) if path else None

            body = NUDGE_BODY.replace("{name}", name).replace("{owner}", owner_name)
            html = _nudge_html(name, owner_name, bool(thumb), caption)

            msg = MIMEMultipart("related")
            msg["Subject"] = NUDGE_SUBJECT.replace("{name}", name).replace("{owner}", owner_name)
            msg["From"] = owner
            msg["To"] = sender_email
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain"))
            alt.attach(MIMEText(html, "html"))
            msg.attach(alt)
            if thumb:
                img = MIMEImage(thumb, "jpeg")
                img.add_header("Content-ID", "<lastphoto>")
                img.add_header("Content-Disposition", "inline", filename="lastphoto.jpg")
                msg.attach(img)

            with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
                server.starttls()
                server.login(owner, config["email_password"])
                server.send_message(msg)
            nlog[sender_email] = now.isoformat()
            sent += 1
            print(f"[Selah] Sent inactivity nudge to {sender_email}")
        except Exception as e:
            log_error(f"Failed to nudge {sender_email}: {e}")

    nlog["_last_run"] = now.isoformat()
    try:
        with open(NUDGE_LOG_FILE, "w") as f:
            json.dump(nlog, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save nudge log: {e}")
    if sent:
        print(f"[Selah] Sent {sent} inactivity nudge(s)")


def send_invitations(config, recipients=None):
    """Send the photo-submission invitation on demand (the "nudge" button).

    recipients defaults to the full approved-senders list. Returns the number
    of invitations actually sent. Safe to call from the config GUI.
    """
    owner = config.get("email_address", "")
    if not owner or not config.get("email_password"):
        log_error("Cannot send invitations: email_address/password not configured")
        return 0

    if recipients is None:
        recipients = load_approved_senders()

    sent = 0
    for sender_email in recipients:
        sender_email = (sender_email or "").strip()
        if not sender_email or sender_email == owner:
            continue
        try:
            name = sender_email.split("@")[0].replace(".", " ").replace("_", " ").title()
            body = (ANNUAL_INVITE_BODY.replace("{name}", name).replace("{email}", owner)
                        .replace("{drive}", _invite_drive_text(config)))
            msg = MIMEText(body)
            msg["Subject"] = ANNUAL_INVITE_SUBJECT
            msg["From"] = owner
            msg["To"] = sender_email

            with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
                server.starttls()
                server.login(owner, config["email_password"])
                server.send_message(msg)
            sent += 1
            print(f"[Selah] Sent invitation to {sender_email}")
        except Exception as e:
            log_error(f"Failed to send invitation to {sender_email}: {e}")
    return sent


DIGEST_LOG_FILE = "digest_log.json"


def send_weekly_digest(config):
    """Once a week, email the owner a short summary of newly added photos.

    Self-throttles: only on weekly_digest_weekday (0=Mon..6=Sun), once per ISO
    week. Reports growth in media_log since the previous digest.
    """
    if not config.get("weekly_digest_enabled", False):
        return
    owner = config.get("email_address", "")
    if not owner or not config.get("email_password"):
        return

    now = datetime.datetime.now()
    if now.weekday() != int(config.get("weekly_digest_weekday", 6)):
        return
    week = now.strftime("%G-W%V")

    last = {}
    try:
        if os.path.exists(DIGEST_LOG_FILE):
            with open(DIGEST_LOG_FILE) as f:
                last = json.load(f)
    except Exception:
        last = {}
    if last.get("week") == week:
        return

    try:
        with open("media_log.json") as f:
            total = len(json.load(f))
    except Exception:
        total = 0
    new_count = max(0, total - int(last.get("total", total)))

    body = (
        "Hi!\n\nHere's your Selah weekly update:\n\n"
        f"  - {new_count} new photo(s) added this week.\n"
        f"  - {total} photos in the display in total.\n\n"
        "Keep the memories coming!\n\n- Selah"
    )
    try:
        msg = MIMEText(body)
        msg["Subject"] = "Selah: your week in photos"
        msg["From"] = owner
        msg["To"] = owner
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(owner, config["email_password"])
            server.send_message(msg)
        with open(DIGEST_LOG_FILE, "w") as f:
            json.dump({"week": week, "total": total, "sent": now.isoformat()}, f)
        print(f"[Selah] Sent weekly digest ({new_count} new)")
    except Exception as e:
        log_error(f"Weekly digest send failed: {e}")


def _load_invite_log():
    """Load the invite log tracking when invites were last sent."""
    try:
        with open(INVITE_LOG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_invite_log(data):
    """Save the invite log."""
    try:
        with open(INVITE_LOG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save invite log: {e}")


def log_media(file_path, sender, date, caption):
    """Log media details to media_log.json."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "file_path": file_path,
            "sender": sender,
            "date": str(date) if date else None,
            "caption": caption
        }
        try:
            with open("media_log.json", "r") as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append(log_entry)
        with open("media_log.json", "w") as f:
            json.dump(log, f, indent=4)
    except Exception as e:
        log_error(f"Media logging failed: {e}", critical=False)
