"""
Google Drive Sync Module for Selah Display System.

Handles two-way sync:
  1. PULL: Download new images/videos from a Google Drive folder to local media dirs
  2. PUSH (backup): Upload local media files to Google Drive

Requires:
  - google-api-python-client
  - google-auth-httplib2
  - google-auth-oauthlib
  - A credentials.json file from Google Cloud Console (OAuth 2.0 client)
  - Drive API enabled in the Google Cloud project

First run will open a browser for OAuth consent; subsequent runs use token.json.
"""

import os
import io
import json
import time
import hashlib
import datetime
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

from modules.logger import log_error

# If modifying scopes, delete token.json so the user re-authorizes.
SCOPES = ["https://www.googleapis.com/auth/drive"]

# MIME types we care about
IMAGE_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
VIDEO_MIMES = {
    "video/mp4": ".mp4",
    "video/x-msvideo": ".avi",
    "video/quicktime": ".mov",
}
ALL_MEDIA_MIMES = {**IMAGE_MIMES, **VIDEO_MIMES}

SYNC_STATE_FILE = "drive_sync_state.json"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_drive_service(config):
    """Authenticate and return a Google Drive API service object."""
    if not GOOGLE_AVAILABLE:
        log_error(
            "Google API libraries not installed. "
            "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
            critical=True, config=config,
        )
        return None

    creds = None
    token_path = config.get("google_token_path", "token.json")
    credentials_path = config.get("google_credentials_path", "credentials.json")

    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            log_error(f"Failed to load token.json: {e}", config=config)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                log_error(f"Token refresh failed: {e}", config=config)
                creds = None

        if not creds:
            if not os.path.exists(credentials_path):
                log_error(
                    f"Missing {credentials_path}. Download OAuth credentials from Google Cloud Console.",
                    critical=True, config=config,
                )
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                log_error(f"OAuth flow failed: {e}", critical=True, config=config)
                return None

        # Save the token for future runs
        try:
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        except Exception as e:
            log_error(f"Failed to save token: {e}", config=config)

    try:
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        log_error(f"Failed to build Drive service: {e}", critical=True, config=config)
        return None


# ---------------------------------------------------------------------------
# Sync state persistence (tracks what we've already downloaded / uploaded)
# ---------------------------------------------------------------------------

def load_sync_state():
    """Load the sync state that tracks downloaded and uploaded file IDs."""
    try:
        with open(SYNC_STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"downloaded": {}, "uploaded": {}}


def save_sync_state(state):
    """Persist sync state to disk."""
    try:
        with open(SYNC_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save sync state: {e}")


# ---------------------------------------------------------------------------
# PULL — Download new media from Google Drive
# ---------------------------------------------------------------------------

def pull_from_drive(config, screens=None):
    """
    Download new images/videos from the configured Google Drive folder(s)
    into the local media directories. Skips files already downloaded.

    Supports one or more source folders — see _get_folder_ids(). A failure in
    one folder doesn't stop the others.

    Returns a list of newly downloaded file paths.
    """
    if not config.get("cloud_backup_enabled", False):
        return []

    folder_ids = _get_folder_ids(config)
    if not folder_ids:
        log_error("Google Drive folder ID(s) not configured.", config=config)
        return []

    service = get_drive_service(config)
    if not service:
        return []

    sync_state = load_sync_state()
    downloaded = sync_state.get("downloaded", {})
    new_files = []

    for folder_id in folder_ids:
        try:
            _pull_one_folder(service, folder_id, config, downloaded, new_files)
        except Exception as e:
            log_error(f"Drive pull failed for folder {folder_id}: {e}", config=config)

    # Persist updated state once, after all folders.
    sync_state["downloaded"] = downloaded
    save_sync_state(sync_state)

    if new_files:
        src = "1 folder" if len(folder_ids) == 1 else f"{len(folder_ids)} folders"
        print(f"[Drive Sync] Downloaded {len(new_files)} new file(s) from {src}.")
    return new_files


def _pull_one_folder(service, folder_id, config, downloaded, new_files):
    """Pull new media from a single Drive folder. Mutates downloaded/new_files."""
    # Build the MIME type query
    mime_queries = " or ".join(
        f"mimeType='{m}'" for m in ALL_MEDIA_MIMES.keys()
    )
    query = f"'{folder_id}' in parents and ({mime_queries}) and trashed=false"

    page_token = None
    while True:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            pageToken=page_token,
            pageSize=100,
        ).execute()

        for file_info in response.get("files", []):
            file_id = file_info["id"]
            if file_id in downloaded:
                continue  # Already have this one

            file_name = file_info["name"]
            mime_type = file_info["mimeType"]
            ext = ALL_MEDIA_MIMES.get(mime_type, "")

            # Ensure file has the right extension
            if not file_name.lower().endswith(tuple(ALL_MEDIA_MIMES.values())):
                base, _ = os.path.splitext(file_name)
                file_name = base + ext

            # Determine destination folder
            dest_dir = Path(config.get("display_dir", "media/display"))

            # Check for subfolder structure in Drive
            # If the file is inside a date-named subfolder, replicate locally
            try:
                parents = service.files().get(
                    fileId=file_id, fields="parents"
                ).execute().get("parents", [])
                if parents and parents[0] != folder_id:
                    parent_info = service.files().get(
                        fileId=parents[0], fields="name"
                    ).execute()
                    parent_name = parent_info.get("name", "")
                    # Check if parent folder looks like a date
                    if _is_date_folder(parent_name):
                        dest_dir = Path(config.get("media_folder", "media")) / parent_name
            except Exception:
                pass  # Fall back to display_dir

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / file_name

            # Avoid overwriting if a file with same name already exists
            if dest_path.exists():
                base, ext_part = os.path.splitext(file_name)
                dest_path = dest_dir / f"{base}_{file_id[:8]}{ext_part}"

            # Download the file
            try:
                request = service.files().get_media(fileId=file_id)
                with open(dest_path, "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

                downloaded[file_id] = {
                    "local_path": str(dest_path),
                    "name": file_name,
                    "source_folder": folder_id,
                    "downloaded_at": datetime.datetime.now().isoformat(),
                }
                new_files.append(str(dest_path))
                print(f"[Drive Sync] Downloaded: {file_name} -> {dest_path}")
            except Exception as e:
                log_error(f"Failed to download {file_name}: {e}", config=config)

        page_token = response.get("nextPageToken")
        if not page_token:
            break


# ---------------------------------------------------------------------------
# PUSH — Backup local media to Google Drive
# ---------------------------------------------------------------------------

def push_to_drive(config, file_paths=None):
    """
    Upload local media files to the configured Google Drive folder.
    If file_paths is None, scans all media directories for files not yet uploaded.

    Returns the count of newly uploaded files.
    """
    if not config.get("cloud_backup_enabled", False):
        return 0

    # Backups go to a single target: an explicit backup folder if set,
    # otherwise the first configured source folder.
    folder_ids = _get_folder_ids(config)
    folder_id = config.get("google_drive_backup_folder_id", "") or (folder_ids[0] if folder_ids else "")
    if not folder_id:
        log_error("Google Drive folder ID not configured.", config=config)
        return 0

    service = get_drive_service(config)
    if not service:
        return 0

    sync_state = load_sync_state()
    uploaded = sync_state.get("uploaded", {})
    upload_count = 0

    # If no specific files given, scan media directories
    if file_paths is None:
        file_paths = _collect_all_local_media(config)

    valid_exts = tuple(config.get("valid_extensions", [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"]))

    for file_path in file_paths:
        file_path = str(file_path)
        if not os.path.isfile(file_path):
            continue
        if not file_path.lower().endswith(valid_exts):
            continue

        # Use file path hash as a stable key to avoid re-uploading
        file_key = _file_key(file_path)
        if file_key in uploaded:
            continue

        try:
            file_name = os.path.basename(file_path)
            mime_type = _guess_mime(file_path)

            file_metadata = {
                "name": file_name,
                "parents": [folder_id],
            }
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
            result = service.files().create(
                body=file_metadata, media_body=media, fields="id"
            ).execute()

            uploaded[file_key] = {
                "drive_id": result["id"],
                "local_path": file_path,
                "uploaded_at": datetime.datetime.now().isoformat(),
            }
            upload_count += 1
            print(f"[Drive Sync] Uploaded: {file_name} (ID: {result['id']})")
        except Exception as e:
            log_error(f"Failed to upload {file_path}: {e}", config=config)

    sync_state["uploaded"] = uploaded
    save_sync_state(sync_state)

    if upload_count:
        print(f"[Drive Sync] Uploaded {upload_count} new file(s) to Google Drive.")
    return upload_count


def backup_single_file(file_path, config):
    """Convenience function to upload a single file to Drive (used by email_handler)."""
    return push_to_drive(config, file_paths=[file_path])


# ---------------------------------------------------------------------------
# Full two-way sync
# ---------------------------------------------------------------------------

def sync_drive(config, screens=None):
    """
    Perform a full two-way sync:
      1. Pull new files from Drive to local
      2. Push local files to Drive
    Returns (new_downloaded, new_uploaded) counts.
    """
    new_files = pull_from_drive(config, screens)
    uploaded_count = push_to_drive(config)
    return len(new_files), uploaded_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_folder_ids(config):
    """Return the list of Drive source folder IDs to pull from.

    Accepts either:
      - google_drive_folder_ids: ["id1", "id2", ...]   (preferred, multi-folder)
      - google_drive_folder_id:  "id"                  (legacy, single folder)
    The list form takes precedence. Placeholders and blanks are dropped and the
    result is de-duplicated while preserving order.
    """
    ids = config.get("google_drive_folder_ids")
    if not ids:
        single = config.get("google_drive_folder_id", "")
        ids = [single] if single else []
    elif isinstance(ids, str):
        ids = [ids]

    placeholders = {"your_folder_id", "your_drive_folder_id", ""}
    seen, out = set(), []
    for fid in ids:
        fid = str(fid).strip()
        if fid in placeholders or fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
    return out


def _is_date_folder(name):
    """Check if a folder name looks like YYYY-MM-DD."""
    try:
        datetime.datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _file_key(file_path):
    """Generate a stable key for a local file based on path + modification time."""
    stat = os.stat(file_path)
    raw = f"{os.path.abspath(file_path)}:{stat.st_size}:{stat.st_mtime}"
    return hashlib.md5(raw.encode()).hexdigest()


def _guess_mime(file_path):
    """Guess MIME type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
    }
    return mime_map.get(ext, "application/octet-stream")


def _collect_all_local_media(config):
    """Collect all media file paths from local media directories."""
    media_folder = config.get("media_folder", "media")
    valid_exts = tuple(config.get("valid_extensions", [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"]))
    files = []
    for path in Path(media_folder).rglob("*"):
        if path.suffix.lower() in valid_exts and path.is_file():
            files.append(str(path))
    return files
