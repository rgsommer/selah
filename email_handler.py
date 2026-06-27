import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from pathlib import Path
import re
import datetime
import json
import time
import os
from email.utils import parsedate_to_datetime
from modules.cloud_backup import backup_to_drive
from modules.leaderboard import update_leaderboard
from modules.toast import show_toast_if_needed

def log_error(message, critical=False, config=None):
    """Log errors to error_log.json and email critical errors."""
    try:
        error_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "message": str(message),
            "critical": critical
        }
        try:
            with open("error_log.json", "r") as f:
                error_log = json.load(f)
        except:
            error_log = []
        error_log.append(error_entry)
        with open("error_log.json", "w") as f:
            json.dump(error_log, f, indent=4)
        
        if critical and config and config.get("error_email_recipient"):
            email_error(config, message)
    except Exception as e:
        print(f"Error logging failed: {e}")

def email_error(config, error_message):
    """Send error email to main user."""
    try:
        msg = MIMEText(f"Critical error in Selah Display System:\n\n{error_message}")
        msg["Subject"] = "Selah Display System Error"
        msg["From"] = config["email_address"]
        msg["To"] = config["error_email_recipient"]
        
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["email_address"], config["email_password"])
            server.send_message(msg)
    except Exception as e:
        log_error(f"Failed to send error email: {e}", critical=False)

def check_for_new_emails(config, screens):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            mail = imaplib.IMAP4_SSL(config["imap_server"])
            mail.login(config["email_address"], config["email_password"])
            mail.select("inbox")
            
            _, data = mail.search(None, "UNSEEN")
            for num in data[0].split():
                _, msg_data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                
                sender = msg["from"]
                approved_senders = load_approved_senders()
                if not any(s in sender for s in approved_senders):
                    log_error(f"Unapproved sender: {sender}", critical=False)
                    continue
                
                subject = msg["subject"]
                date = parse_subject_date(subject)
                if not date:
                    date = get_email_date(msg)
                
                caption = ""
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        caption = extract_caption(body)
                    if part.get_content_disposition() == "attachment":
                        filename = part.get_filename()
                        if filename and filename.lower().endswith(tuple(config["valid_extensions"])):
                            file_path = save_attachment(part, config, date)
                            if file_path:
                                final_date = date or get_file_date(file_path)
                                queue_media(file_path, final_date, caption, config)
                                send_auto_reply(sender, config, final_date)
                                update_leaderboard(sender, 1)
                                backup_to_drive(file_path, config)
                                show_toast_if_needed(screens, config, f"New media from {sender}")
                                log_media(file_path, sender, final_date, caption)
            
            mail.logout()
            break
        except Exception as e:
            error_msg = f"Email check failed (attempt {attempt + 1}/{max_retries}): {e}"
            log_error(error_msg, critical=(attempt == max_retries - 1), config=config)
            if attempt == max_retries - 1:
                show_toast_if_needed(screens, config, "Email check failed. Check credentials.")
            time.sleep(5)

def parse_subject_date(subject):
    """Extract date from email subject."""
    date_patterns = [r"(\w+ \d{1,2})", r"(\d{4}-\d{2}-\d{2})"]
    for pattern in date_patterns:
        match = re.search(pattern, subject, re.I)
        if match:
            try:
                date_str = match.group(1)
                if "-" in date_str:
                    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    return datetime.datetime.strptime(f"{date_str} {datetime.datetime.now().year}", "%B %d %Y").date()
            except ValueError:
                continue
    return None

def get_email_date(msg):
    """Get sent date from email headers."""
    try:
        date_str = msg["Date"]
        if date_str:
            parsed_date = parsedate_to_datetime(date_str)
            return parsed_date.date()
    except Exception as e:
        log_error(f"Failed to parse email date: {e}", critical=False)
    return None

def get_file_date(file_path):
    """Get file creation date as fallback."""
    try:
        ctime = os.path.getctime(file_path)
        return datetime.datetime.fromtimestamp(ctime).date()
    except Exception as e:
        log_error(f"Failed to get file date: {e}", critical=False)
        return datetime.datetime.now().date()

def extract_caption(body):
    """Extract first sentence from email body."""
    try:
        sentences = re.split(r'[.!?]+', body)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                return sentence
        return ""
    except Exception as e:
        log_error(f"Caption extraction failed: {e}", critical=False)
        return ""

def save_attachment(part, config, date):
    """Save attachment to appropriate folder."""
    try:
        filename = part.get_filename()
        folder = config["media_folder"]
        if date:
            folder = Path(folder) / str(date)
            folder.mkdir(exist_ok=True)
        else:
            folder = Path(folder) / "display"
            folder.mkdir(exist_ok=True)
        file_path = folder / filename
        with open(file_path, "wb") as f:
            f.write(part.get_payload(decode=True))
        return str(file_path)
    except Exception as e:
        log_error(f"Failed to save attachment: {e}", critical=True, config=config)
        return None

def queue_media(file_path, date, caption, config):
    """Queue media for display."""
    try:
        if not date and config.get("immediate_display", False):
            print(f"Immediately displaying: {file_path}")
        else:
            print(f"Queued: {file_path} for {date} with caption: {caption}")
    except Exception as e:
        log_error(f"Failed to queue media: {e}", critical=False)

def send_auto_reply(sender, config, date):
    """Send auto-reply to sender."""
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
        log_error(f"Failed to send auto-reply: {e}", critical=True, config=config)

def get_custom_response(sender, date, config):
    """Get custom email response."""
    try:
        if not config.get("custom_email_responses", False):
            return f"Thank you for your submission! It is queued for {date or 'immediate display'}."
        with open("email_responses.json", "r") as f:
            responses = json.load(f)
        for response in responses:
            condition = response["condition"]
            if condition == "immediate" and not date:
                return response["message"]
            if condition == "scheduled" and date:
                return response["message"].format(date=date)
            if condition.startswith("sender:") and condition.split(":")[1] in sender:
                return response["message"]
            if condition == "default":
                return response["message"].format(date=date or "immediate display")
        return "Thank you for your submission!"
    except Exception as e:
        log_error(f"Custom response failed: {e}", critical=False)
        return f"Thank you for your submission! It is queued for {date or 'immediate display'}."

def load_approved_senders(path="approved_senders.json"):
    """Load approved senders list."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log_error(f"Failed to load approved senders: {e}", critical=False)
        return []

def log_media(file_path, sender, date, caption):
    """Log media details."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "file_path": file_path,
            "sender": sender,
            "date": str(date),
            "caption": caption
        }
        try:
            with open("media_log.json", "r") as f:
                log = json.load(f)
        except:
            log = []
        log.append(log_entry)
        with open("media_log.json", "w") as f:
            json.dump(log, f, indent=4)
    except Exception as e:
        log_error(f"Media logging failed: {e}", critical=False)
