"""Google Drive cloud backup for submitted media."""

import os
from modules.logger import log_error


def backup_to_drive(file_path, config):
    """Upload a file to Google Drive if backup is enabled and credentials exist."""
    if not config.get("cloud_backup_enabled", False):
        return

    folder_id = config.get("google_drive_folder_id", "")
    if not folder_id or folder_id == "your_folder_id":
        return

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = _get_credentials()
        if not creds:
            log_error("No valid Google Drive credentials for backup")
            return

        service = build("drive", "v3", credentials=creds)

        filename = os.path.basename(file_path)
        file_metadata = {
            "name": filename,
            "parents": [folder_id]
        }

        ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".mp4": "video/mp4",
            ".avi": "video/x-msvideo", ".mov": "video/quicktime",
        }
        mime_type = mime_types.get(ext, "application/octet-stream")

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()

        print(f"[Selah] Backed up to Google Drive: {filename}")

    except ImportError:
        log_error("Google API client not installed - backup disabled")
    except Exception as e:
        log_error(f"Google Drive backup failed: {e}")


def _get_credentials():
    """Load Google OAuth2 credentials from token.json."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json")
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open("token.json", "w") as f:
                    f.write(creds.to_json())
            return creds
    except Exception as e:
        log_error(f"Failed to load Google credentials: {e}")
    return None
