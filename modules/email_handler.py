"""Email intake: checks IMAP for new photos/videos, saves attachments,
sends auto-replies, and coordinates with leaderboard/backup/toast modules."""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import datetime
import json
import time
import os
from modules.logger import log_error

# Re-export log_error so existing imports from modules.email_handler still work
__all__ = ["check_for_new_emails", "log_error"]


def check_for_new_emails(config, screens):
    """Check Gmail for new unread emails with media attachments."""
    if not config.get("email_address") or not config.get("email_password"):
        return
    if config.get("email_password") == "your-app-specific-password":
        return  # Placeholder password, skip

    max_retries = 3
    for attempt in range(max_retries):
        try:
            mail = imaplib.IMAP4_SSL(config["imap_server"])
            mail.login(config["email_address"], config["email_password"])
            mail.select("inbox")

            _, data = mail.search(None, "UNSEEN")
            if not data[0]:
                mail.logout()
                return

            for num in data[0].split():
                _, msg_data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                sender = msg.get("from", "")
                subject = msg.get("subject", "")

                # Check for approval replies first
                if _is_approval_reply(subject, msg, config):
                    continue

                approved_senders = load_approved_senders()
                if approved_senders and not any(s in sender for s in approved_senders):
                    _handle_unapproved_sender(sender, msg, config, screens)
                    continue

                date = parse_subject_date(subject)
                if not date:
                    date = get_email_date(msg)

                caption = ""
                has_attachment = False
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode(errors="replace")
                            caption = extract_caption(body)
                        except Exception:
                            pass
                    if part.get_content_disposition() == "attachment":
                        filename = part.get_filename()
                        if filename and filename.lower().endswith(
                            tuple(config.get("valid_extensions", []))
                        ):
                            file_path = save_attachment(part, config, date)
                            if file_path:
                                has_attachment = True
                                final_date = date or get_file_date(file_path)
                                queue_media(file_path, final_date, caption, config)
                                send_auto_reply(sender, config, final_date)
                                # Lazy imports to avoid circular dependencies
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
                                    from modules.toast import queue_toast
                                    queue_toast(f"New photo from {sender.split('<')[0].strip()}")
                                except Exception:
                                    pass
                                log_media(file_path, sender, final_date, caption)

            mail.logout()
            break

        except Exception as e:
            error_msg = f"Email check failed (attempt {attempt + 1}/{max_retries}): {e}"
            log_error(error_msg, critical=(attempt == max_retries - 1), config=config)
            if attempt == max_retries - 1:
                try:
                    from modules.toast import queue_toast
                    queue_toast("Email check failed. Check credentials.")
                except Exception:
                    pass
            time.sleep(5)


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
    # Try month+day: May 10, Oct 15, January 1
    month_day = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2})",
        subject, re.I
    )
    if month_day:
        try:
            month_str = month_day.group(1)
            day_str = month_day.group(2)
            year = datetime.datetime.now().year
            # Try full month name first, then abbreviated
            for fmt in ["%B %d %Y", "%b %d %Y"]:
                try:
                    return datetime.datetime.strptime(f"{month_str} {day_str} {year}", fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass
    return None


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


def save_attachment(part, config, date):
    """Save email attachment to the appropriate media folder."""
    try:
        filename = part.get_filename()
        if not filename:
            return None
        folder = Path(config.get("media_folder", "media"))
        if date:
            folder = folder / str(date)
        else:
            folder = folder / "display"
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


def send_auto_reply(sender, config, date):
    """Send auto-reply to contributor."""
    if not config.get("email_address") or not config.get("email_password"):
        return
    try:
        message = get_custom_response(sender, date, config)
        msg = MIMEText(message)
        msg["Subject"] = "Selah Submission Received"
        msg["From"] = config["email_address"]
        msg["To"] = sender

        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["email_address"], config["email_password"])
            server.send_message(msg)
    except Exception as e:
        log_error(f"Failed to send auto-reply: {e}", critical=False, config=config)


def get_custom_response(sender, date, config):
    """Get custom email response from templates."""
    try:
        if not config.get("custom_email_responses", False):
            return f"Thank you for your submission! It is queued for {date or 'immediate display'}."
        try:
            with open("email_responses.json", "r") as f:
                responses = json.load(f)
        except FileNotFoundError:
            return f"Thank you for your submission! It is queued for {date or 'immediate display'}."

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
        return "Thank you for your submission!"
    except Exception:
        return f"Thank you for your submission! It is queued for {date or 'immediate display'}."


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

SENDING A BIRTHDAY (OR ANNIVERSARY) GREETING — plan ahead!
You don't have to remember on the day. Email your photo a few days early
(say 3 days before) and put the person's name and date in the subject line:

      Subject: Happy Birthday, Mom Sept 4

Your greeting is saved and shown FIRST THING on the morning of Sept 4 —
together with everyone else's greetings for that day, and favourite photos
that feature the birthday person. Other date formats work too:

      Subject: Merry Christmas 2026-12-25
      Subject: Happy Anniversary, Mom & Dad June 15

We'd love to see your photos up on the screen. Send as many as you like!

- The Selah Family Display
"""


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

    # Toast notification
    try:
        from modules.toast import queue_toast
        queue_toast(f"Approval needed: {sender_name}")
    except Exception:
        pass

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

    sent_count = 0
    for sender_email in senders:
        # Skip the system's own email
        if sender_email == owner:
            continue

        # Derive a friendly name from the email
        name = sender_email.split("@")[0].replace(".", " ").replace("_", " ").title()

        try:
            body = ANNUAL_INVITE_BODY.replace("{name}", name).replace("{email}", owner)
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
            body = ANNUAL_INVITE_BODY.replace("{name}", name).replace("{email}", owner)
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
