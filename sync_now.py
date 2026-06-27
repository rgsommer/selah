#!/usr/bin/env python3
"""One-shot full two-way Google Drive sync (no per-cycle cap).

Run this on the Pi to seed/mirror the whole library in one go:

    python3 sync_now.py

The live display loop also syncs continuously, but it caps uploads per cycle so
it never freezes the slideshow — that's slow for a first-time backup of a big
library. This script does the full push/pull at once with progress output.

Requires the Google libraries, credentials.json, and a valid token.json (run
the display once to authorize, or authorize here on first run).
"""

import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config
from modules.google_drive_sync import pull_from_drive, push_to_drive, _get_folder_ids


def main():
    cfg = load_config("display_config.json")

    if not cfg.get("cloud_backup_enabled"):
        print("cloud_backup_enabled is false in display_config.json — enable it first.")
        return

    sources = _get_folder_ids(cfg)
    backup = cfg.get("google_drive_backup_folder_id", "") or (sources[0] if sources else "")
    print(f"Pull source folder(s): {sources or '(none configured)'}")
    print(f"Push/backup target   : {backup or '(none configured)'}")
    if not sources and not backup:
        print("No Drive folders configured — set google_drive_folder_ids first.")
        return

    print("\nPulling new photos from Drive -> local ...")
    downloaded = pull_from_drive(cfg)
    print(f"  downloaded {len(downloaded)} new file(s)")

    print("\nPushing local library -> Drive (this can take a long time for big libraries) ...")
    uploaded = push_to_drive(cfg, max_uploads=None)  # unlimited
    print(f"  uploaded {uploaded} new file(s)")

    print("\nDone. The display loop will keep both sides in sync from here on.")


if __name__ == "__main__":
    main()
