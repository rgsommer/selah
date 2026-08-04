#!/usr/bin/env python3
"""Verify the Google Drive folder(s) Selah is configured to sync: print each
folder's NAME and its most recent files, so you can confirm it's the folder you
dropped photos into (e.g. /uploads).

    python3 drive_check.py
    python3 drive_check.py <folderId>   # also inspect a specific folder id
"""

import os
import sys
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.google_drive_sync import get_drive_service, _get_folder_ids


def _describe(service, fid):
    try:
        meta = service.files().get(
            fileId=fid, fields="id, name, mimeType", supportsAllDrives=True).execute()
    except Exception as e:
        print(f"  {fid}\n    ERROR: {e}  (wrong id, or this account can't see it)")
        return
    name = meta.get("name", "?")
    is_folder = meta.get("mimeType") == "application/vnd.google-apps.folder"
    print(f"  {fid}\n    name: {name!r}  {'(folder)' if is_folder else '(NOT a folder!)'}")
    if not is_folder:
        return
    try:
        resp = service.files().list(
            q=f"'{fid}' in parents and trashed=false",
            spaces="drive", orderBy="modifiedTime desc", pageSize=12,
            fields="files(name, mimeType, modifiedTime)",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = resp.get("files", [])
    except Exception as e:
        print(f"    could not list contents: {e}")
        return
    imgs = [f for f in files if not f.get("mimeType", "").endswith("folder")]
    print(f"    {len(files)} item(s) shown (most recent first):")
    for f in files[:12]:
        kind = "DIR " if f.get("mimeType", "").endswith("folder") else "file"
        when = (f.get("modifiedTime", "") or "")[:16].replace("T", " ")
        print(f"      [{kind}] {when}  {f.get('name', '?')}")
    if not imgs:
        print("    (no files directly here — your photos may be in a SUBFOLDER; "
              "Selah pulls this folder recursively, so that's fine)")


def main():
    cfg = load_config("display_config.json")
    print(f"cloud_backup_enabled = {cfg.get('cloud_backup_enabled')}   "
          f"(sync must be True for Selah to pull)\n")
    if not os.path.exists("token.json"):
        print("No token.json — run:  python3 authorize.py")
        return
    service = get_drive_service(cfg)
    if not service:
        print("Could not connect to Google Drive.")
        return

    # Which account is this token?
    try:
        about = service.about().get(fields="user(emailAddress)").execute()
        print(f"Drive account: {about.get('user', {}).get('emailAddress', '?')}\n")
    except Exception:
        pass

    ids = _get_folder_ids(cfg)
    print(f"Selah is configured to sync {len(ids)} folder(s):")
    for fid in ids:
        _describe(service, fid)

    extra = [a for a in sys.argv[1:] if a and not a.startswith("-")]
    if extra:
        print("\nAlso inspecting the id(s) you passed:")
        for fid in extra:
            _describe(service, fid)
    print("\nTip: open your /uploads folder in a browser — the URL ends in "
          "…/folders/<THIS-IS-THE-ID>. It should match a folder id above.")


if __name__ == "__main__":
    main()
