#!/usr/bin/env python3
"""One-shot Google Drive sync.

    python3 sync_now.py          # pull from Drive (+ push only if enabled)
    python3 sync_now.py push     # force the full local -> Drive upload

By default this PULLS (downloads new Drive/family-folder photos) and only
pushes the local library up if drive_push_enabled is true — so it never
surprise-uploads a big archive into your shared folder. The first run also
opens a browser to authorize Google.
"""

import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.google_drive_sync import (
    pull_from_drive, pull_family_folder, push_to_drive, _get_folder_ids,
)


def main():
    cfg = load_config("display_config.json")
    if not cfg.get("cloud_backup_enabled"):
        print("cloud_backup_enabled is false in display_config.json — enable it first.")
        return

    force_push = "push" in sys.argv[1:]
    sources = _get_folder_ids(cfg)
    backup = cfg.get("google_drive_backup_folder_id", "") or (sources[0] if sources else "")
    print(f"Pull source folder(s): {sources or '(none configured)'}")

    print("\nPulling new photos from Drive -> local ...")
    downloaded = pull_from_drive(cfg)
    downloaded += pull_family_folder(cfg) or []
    print(f"  downloaded {len(downloaded)} new file(s)")

    if force_push or cfg.get("drive_push_enabled", False):
        print(f"\nPushing local library -> Drive folder {backup or '(none)'} ...")
        print("  (this can take a long time for a large library)")
        uploaded = push_to_drive(cfg, max_uploads=None)
        print(f"  uploaded {uploaded} new file(s)")
    else:
        print("\nPush skipped (drive_push_enabled is off) — your local library was")
        print("not uploaded. To back it up to Drive, set a backup folder and run:")
        print("    python3 sync_now.py push")

    print("\nDone.")


if __name__ == "__main__":
    main()
