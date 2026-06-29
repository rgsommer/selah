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
import threading
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
_IMAGE_EXTS = (".jpg", ".jpeg", ".png")

SYNC_STATE_FILE = "drive_sync_state.json"


def build_media_index(config):
    """Set of lowercased filenames already present anywhere under the media
    folder. Used to skip re-downloading photos that are already on disk (e.g.
    an rsync'd library) when the Drive sync state doesn't yet know their IDs."""
    root = config.get("media_folder", "media")
    index = set()
    try:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                index.add(f.lower())
    except Exception as e:
        log_error(f"Media index build failed: {e}")
    return index


def _maybe_downscale(path, config):
    """Shrink a just-downloaded image to a max long edge so 12MP+ originals
    don't fill the disk. No-op for video, small images, or if disabled."""
    if not config.get("drive_downscale_enabled", True):
        return
    p = str(path)
    if not p.lower().endswith(_IMAGE_EXTS):
        return
    max_edge = int(config.get("drive_downscale_max_px", 2560))
    try:
        from PIL import Image, ImageOps
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)  # bake rotation in before stripping EXIF
            w, h = im.size
            if max(w, h) <= max_edge:
                return  # already small enough
            scale = max_edge / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            if p.lower().endswith(".png"):
                im.save(p, optimize=True)
            else:
                im.convert("RGB").save(p, "JPEG", quality=85, optimize=True)
    except Exception as e:
        log_error(f"Downscale failed for {p}: {e}")


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
    media_index = build_media_index(config)

    for folder_id in folder_ids:
        try:
            _pull_one_folder(service, folder_id, config, downloaded, new_files, media_index)
        except Exception as e:
            log_error(f"Drive pull failed for folder {folder_id}: {e}", config=config)

    # Persist updated state once, after all folders.
    sync_state["downloaded"] = downloaded
    save_sync_state(sync_state)

    if new_files:
        src = "1 folder" if len(folder_ids) == 1 else f"{len(folder_ids)} folders"
        print(f"[Drive Sync] Downloaded {len(new_files)} new file(s) from {src}.")
    return new_files


def _pull_one_folder(service, folder_id, config, downloaded, new_files,
                     media_index=None, subpath=""):
    """Pull media from a Drive folder into media/shared_drive, recursing into
    subfolders so the local tree mirrors Drive exactly. Mutates downloaded/
    new_files."""
    media_index = media_index or set()
    drive_root = Path(config.get("drive_pull_dir", "media/shared_drive"))

    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
            pageSize=100,
        ).execute()

        for file_info in response.get("files", []):
            mime_type = file_info.get("mimeType", "")
            file_name = file_info.get("name", "")

            # Recurse into subfolders, replicating the path under shared_drive.
            if mime_type == "application/vnd.google-apps.folder":
                _pull_one_folder(service, file_info["id"], config, downloaded,
                                 new_files, media_index,
                                 os.path.join(subpath, file_name))
                continue
            if mime_type not in ALL_MEDIA_MIMES:
                continue

            file_id = file_info["id"]
            if file_id in downloaded:
                continue  # Already have this one

            ext = ALL_MEDIA_MIMES.get(mime_type, "")
            if not file_name.lower().endswith(tuple(ALL_MEDIA_MIMES.values())):
                file_name = os.path.splitext(file_name)[0] + ext

            # Already have this file on disk (e.g. an rsync'd library)? Record
            # its ID so we never re-download it, and skip.
            if file_name.lower() in media_index:
                downloaded[file_id] = {
                    "name": file_name, "have_local": True,
                    "downloaded_at": datetime.datetime.now().isoformat(),
                }
                continue

            dest_dir = drive_root / subpath if subpath else drive_root
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / file_name
            if dest_path.exists():
                base, ext_part = os.path.splitext(file_name)
                dest_path = dest_dir / f"{base}_{file_id[:8]}{ext_part}"

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
                _maybe_downscale(dest_path, config)
                new_files.append(str(dest_path))
                print(f"[Drive Sync] Downloaded: {os.path.join(subpath, file_name)}")
            except Exception as e:
                log_error(f"Failed to download {file_name}: {e}", config=config)

        page_token = response.get("nextPageToken")
        if not page_token:
            break


# ---------------------------------------------------------------------------
# Family/Friends folder — a shared Drive folder others upload to
# ---------------------------------------------------------------------------

FAMILY_DIR = "media/family"


def _clean_id(raw):
    """Accept a raw folder ID or a pasted Drive share link."""
    s = (raw or "").strip()
    if "/folders/" in s:
        s = s.split("/folders/")[1]
    elif "id=" in s:
        s = s.split("id=")[1]
    return s.split("?")[0].split("/")[0]


def pull_family_folder(config):
    """Pull the Family/Friends Drive folder into media/family/, preserving each
    contributor's subfolder. Files whose name carries a date are scheduled to
    show on that day (recurring or one-year, per family_folder_recurring)
    instead of joining the normal rotation. Returns newly downloaded paths.
    """
    if not config.get("family_folder_enabled", False):
        return []
    fid = _clean_id(config.get("family_folder_id"))
    if not fid or fid in ("your_folder_id", "your_drive_folder_id"):
        return []
    service = get_drive_service(config)
    if not service:
        return []

    sync_state = load_sync_state()
    downloaded = sync_state.get("downloaded", {})
    new_files = []
    recurring = config.get("family_folder_recurring", True)
    try:
        _pull_family_recursive(service, fid, "", config, downloaded, new_files, recurring)
    except Exception as e:
        log_error(f"Family folder pull failed: {e}", config=config)

    sync_state["downloaded"] = downloaded
    save_sync_state(sync_state)
    if new_files:
        print(f"[Drive Sync] Family folder: {len(new_files)} new file(s)")
    return new_files


def _pull_family_recursive(service, folder_id, subpath, config, downloaded, new_files, recurring):
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token, pageSize=100,
        ).execute()

        for f in resp.get("files", []):
            mime = f.get("mimeType", "")
            name = f.get("name", "")
            if mime == "application/vnd.google-apps.folder":
                _pull_family_recursive(service, f["id"], os.path.join(subpath, name),
                                       config, downloaded, new_files, recurring)
                continue
            if mime not in ALL_MEDIA_MIMES:
                continue
            file_id = f["id"]
            if file_id in downloaded:
                continue

            ext = ALL_MEDIA_MIMES.get(mime, "")
            if not name.lower().endswith(tuple(ALL_MEDIA_MIMES.values())):
                name = os.path.splitext(name)[0] + ext

            dest_dir = Path(FAMILY_DIR) / subpath if subpath else Path(FAMILY_DIR)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / name
            if dest_path.exists():
                b, e = os.path.splitext(name)
                dest_path = dest_dir / f"{b}_{file_id[:8]}{e}"

            try:
                req = service.files().get_media(fileId=file_id)
                with open(dest_path, "wb") as fh:
                    dl = MediaIoBaseDownload(fh, req)
                    done = False
                    while not done:
                        _, done = dl.next_chunk()
                _maybe_downscale(dest_path, config)
                downloaded[file_id] = {
                    "local_path": str(dest_path), "name": name,
                    "downloaded_at": datetime.datetime.now().isoformat(),
                }
                new_files.append(str(dest_path))

                # Date in the filename -> schedule it for its day.
                try:
                    from modules.scheduled_media import parse_filename, add_scheduled
                    mmdd, iso, cap = parse_filename(name)
                    if mmdd:
                        add_scheduled(str(dest_path), mmdd, caption=cap,
                                      recurring=recurring, target_iso=iso)
                except Exception as e:
                    log_error(f"Schedule parse failed for {name}: {e}")
            except Exception as e:
                log_error(f"Failed to download family file {name}: {e}", config=config)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def ensure_family_subfolders(config):
    """Create a subfolder per contact inside the family folder (best-effort)."""
    if not config.get("family_folder_enabled", False):
        return
    fid = _clean_id(config.get("family_folder_id"))
    if not fid:
        return
    service = get_drive_service(config)
    if not service:
        return
    try:
        from modules.contacts import load_contacts
        names = [(c.get("name") or (c.get("email", "").split("@")[0])) for c in load_contacts()]
    except Exception:
        names = []
    names = [n for n in names if n]
    if not names:
        return
    try:
        existing = set()
        resp = service.files().list(
            q=(f"'{fid}' in parents and "
               "mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(name)", pageSize=200).execute()
        for f in resp.get("files", []):
            existing.add(f.get("name", "").lower())
        for name in names:
            if name.lower() not in existing:
                service.files().create(body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [fid],
                }, fields="id").execute()
                print(f"[Drive] Created family subfolder: {name}")
    except Exception as e:
        log_error(f"ensure_family_subfolders failed: {e}", config=config)


# ---------------------------------------------------------------------------
# PUSH — Backup local media to Google Drive
# ---------------------------------------------------------------------------

def _ensure_drive_folder_path(service, root_id, rel_dir, cache):
    """Return the Drive folder ID for `rel_dir` (e.g. 'display/Birds') beneath
    root_id, creating subfolders as needed so the upload mirrors the local tree.
    `cache` maps a relative path -> folder id to avoid repeat lookups."""
    if not rel_dir or rel_dir in (".", ""):
        return root_id
    parent = root_id
    parts = []
    for name in rel_dir.replace("\\", "/").split("/"):
        if not name or name == ".":
            continue
        parts.append(name)
        key = "/".join(parts)
        if key in cache:
            parent = cache[key]
            continue
        # Find an existing subfolder with this name under `parent`.
        safe = name.replace("'", "\\'")
        q = (f"name='{safe}' and '{parent}' in parents and "
             "mimeType='application/vnd.google-apps.folder' and trashed=false")
        resp = service.files().list(q=q, spaces="drive",
                                    fields="files(id)", pageSize=1).execute()
        found = resp.get("files", [])
        if found:
            parent = found[0]["id"]
        else:
            created = service.files().create(body={
                "name": name, "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent],
            }, fields="id").execute()
            parent = created["id"]
            print(f"[Drive] Created folder: {key}")
        cache[key] = parent
    return parent


def push_to_drive(config, file_paths=None, max_uploads=None):
    """
    Upload local media files to the configured Google Drive folder.
    If file_paths is None, scans all media directories for files not yet uploaded.

    max_uploads caps how many files this call uploads (None = unlimited). The
    live display loop passes a small cap so a huge first-time backup is spread
    over many cycles instead of freezing the slideshow; sync_now.py passes None.

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
    # Mirror the local folder structure into Drive (default on) so uploads land
    # in the same subfolders they live in locally.
    mirror = config.get("drive_mirror_structure", True)
    shared_root = os.path.abspath(config.get("drive_pull_dir", "media/shared_drive"))
    media_root = os.path.abspath(config.get("media_folder", "media"))
    folder_cache = {}

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

            parent_id = folder_id
            if mirror:
                try:
                    ap = os.path.abspath(file_path)
                    # Files in the shared mirror map to the Drive folder root
                    # (so export structure == import structure, no wrapper).
                    if ap.startswith(shared_root + os.sep):
                        base = shared_root
                    elif ap.startswith(media_root + os.sep):
                        base = media_root
                    else:
                        base = os.path.dirname(ap)
                    rel_dir = os.path.dirname(os.path.relpath(ap, base))
                    parent_id = _ensure_drive_folder_path(service, folder_id, rel_dir, folder_cache)
                except Exception as e:
                    log_error(f"Mirror path failed for {file_path}: {e}", config=config)
                    parent_id = folder_id

            file_metadata = {
                "name": file_name,
                "parents": [parent_id],
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
            if max_uploads and upload_count >= max_uploads:
                break
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
    # Family/Friends folder (separate source; dated files get scheduled).
    family_new = pull_family_folder(config) or []
    if family_new:
        new_files = list(new_files) + family_new
    # Push (back up local -> Drive) only when explicitly enabled, so we never
    # surprise-upload a large archive. Capped per cycle so it never freezes the
    # slideshow; sync_now.py push uploads unlimited.
    uploaded_count = 0
    if config.get("drive_push_enabled", False):
        uploaded_count = push_to_drive(config, max_uploads=config.get("drive_upload_batch", 200))
    # 3rd value = additions to the shared Family/Friends folder (the "someone
    # uploaded" signal), kept separate from the personal-folder bulk sync.
    return len(new_files), uploaded_count, len(family_new)


# ---------------------------------------------------------------------------
# Background sync — keeps the slideshow running while photos download.
# ---------------------------------------------------------------------------
_sync_thread = None
_sync_lock = threading.Lock()
_sync_result = None      # (downloaded, uploaded, family_added), consumed once


def is_syncing():
    """True while a background sync is in progress."""
    return _sync_thread is not None and _sync_thread.is_alive()


def start_background_sync(config):
    """Kick off sync_drive on a daemon thread. Returns False if one is already
    running (so the caller doesn't pile up overlapping syncs)."""
    global _sync_thread
    if is_syncing():
        return False

    def _run():
        global _sync_result
        try:
            res = sync_drive(config)
        except Exception as e:
            log_error(f"Background drive sync failed: {e}", config=config)
            res = (0, 0, 0)
        with _sync_lock:
            _sync_result = res

    _sync_thread = threading.Thread(target=_run, name="drive-sync", daemon=True)
    _sync_thread.start()
    return True


def take_sync_result():
    """Return and clear the last finished sync's (downloaded, uploaded,
    family_added) tuple, or None if nothing has finished since last call."""
    global _sync_result
    with _sync_lock:
        res, _sync_result = _sync_result, None
    return res


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


def _push_source_dirs(config):
    """Local folders that push uploads from. Defaults to the shared_drive
    mirror; set drive_push_dirs (e.g. ["media/display"]) to push your library
    up to Drive instead/as well. Paths mirror to Drive relative to the media
    folder, so media/display/Birds -> Drive/display/Birds."""
    dirs = config.get("drive_push_dirs") or [config.get("drive_pull_dir", "media/shared_drive")]
    return [d for d in dirs if d]


def _collect_all_local_media(config):
    """Collect media files to push from the configured push source folder(s).

    By default that's media/shared_drive (the two-way mirror). The rsync'd
    library (media/display) is local-only unless you add it to drive_push_dirs.
    The recursive pull's name-dedup keeps anything already local from looping
    back, so pushing the library up is safe."""
    valid_exts = tuple(config.get("valid_extensions", [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"]))
    files = []
    for root in _push_source_dirs(config):
        for path in Path(root).rglob("*"):
            if path.suffix.lower() in valid_exts and path.is_file():
                files.append(str(path))
    return files
