"""Standalone logging module to avoid circular imports."""

import datetime
import json
import smtplib
from email.mime.text import MIMEText


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
        except Exception:
            error_log = []
        error_log.append(error_entry)
        with open("error_log.json", "w") as f:
            json.dump(error_log, f, indent=4)

        if critical and config and config.get("error_email_recipient"):
            _email_error(config, message)
    except Exception as e:
        print(f"[Selah] Error logging failed: {e}")


def _email_error(config, error_message):
    """Send error email to admin."""
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
        print(f"[Selah] Failed to send error email: {e}")
