#!/usr/bin/env python3
"""Backfill photo dates: set each file's modified-time to when the photo was
actually TAKEN, so the on-screen date (and recency/sorting) reflect the picture
date rather than the download/upload date.

Source of truth, in order: the file's own EXIF capture date; then — with
--drive — Google Drive's metadata (imageMediaMetadata.time, else createdTime)
for files that have no local EXIF.

    python3 backfill_dates.py                  # dry run over media/shared_drive
    python3 backfill_dates.py --apply
    python3 backfill_dates.py --all --apply    # whole media tree
    python3 backfill_dates.py --drive --apply  # also ask Drive for EXIF-less files
"""

import os
import sys
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config

IMG_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff",
            ".webp", ".bmp", ".gif")


def _exif_timestamp(path):
    """Capture time from EXIF (DateTimeOriginal/Digitized/DateTime), or None."""
    try:
        from PIL import Image
        try:
            import modules.heif_support  # noqa: F401  (register HEIC)
        except Exception:
            pass
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get(306)                      # DateTime
            try:
                sub = ex.get_ifd(0x8769)           # Exif IFD
                raw = sub.get(36867) or sub.get(36868) or raw
            except Exception:
                pass
        if raw:
            return datetime.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    return None


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    scan_all = "--all" in args
    use_drive = "--drive" in args

    cfg = load_config("display_config.json")
    root = (cfg.get("media_folder", "media") if scan_all
            else cfg.get("drive_pull_dir", "media/shared_drive"))
    if not os.path.isdir(root):
        print(f"No such folder: {root}")
        return

    files = [os.path.join(dp, f)
             for dp, _d, fs in os.walk(root)
             for f in fs if f.lower().endswith(IMG_EXTS)]
    print(f"Scanning {len(files)} image(s) under {root}\n")

    drive_svc = drive_rev = None
    if use_drive:
        try:
            from modules.google_drive_sync import get_drive_service, load_sync_state
            drive_svc = get_drive_service(cfg)
            state = load_sync_state()
            drive_rev = {}
            for fid, info in (state.get("downloaded") or {}).items():
                lp = info.get("local_path")
                if lp:
                    drive_rev[os.path.abspath(lp)] = fid
            print(f"Drive: {len(drive_rev)} downloaded-file mapping(s) for EXIF-less files\n")
        except Exception as e:
            print("Drive lookup unavailable:", e, "\n")
            use_drive = False

    def _drive_ts(path):
        fid = drive_rev.get(os.path.abspath(path)) if drive_rev else None
        if not fid:
            return None, None
        try:
            meta = drive_svc.files().get(
                fileId=fid, fields="imageMediaMetadata/time,createdTime",
                supportsAllDrives=True).execute()
        except Exception:
            return None, None
        t = (meta.get("imageMediaMetadata") or {}).get("time")
        if t:
            try:
                return datetime.datetime.strptime(str(t)[:19], "%Y:%m:%d %H:%M:%S").timestamp(), "drive-exif"
            except Exception:
                pass
        ct = meta.get("createdTime")
        if ct:
            try:
                return datetime.datetime.fromisoformat(str(ct).replace("Z", "+00:00")).timestamp(), "drive-created"
            except Exception:
                pass
        return None, None

    fixed = drivefixed = already = norecover = 0
    shown = 0
    for p in files:
        ts, src = _exif_timestamp(p), "exif"
        if ts is None and use_drive:
            ts, src = _drive_ts(p)
        if ts is None:
            norecover += 1
            continue
        try:
            cur = os.path.getmtime(p)
        except Exception:
            cur = 0
        if abs(cur - ts) < 86400:            # already within a day — leave it
            already += 1
            continue
        d = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if apply:
            try:
                os.utime(p, (ts, ts))
            except Exception as e:
                print(f"  utime failed: {p}: {e}")
                continue
        fixed += 1
        if src.startswith("drive"):
            drivefixed += 1
        if shown < 20:
            shown += 1
            print(f"  {'set ' if apply else 'would set'} {d}  ({src})  {os.path.relpath(p)}")
    if fixed > shown:
        print(f"  ... and {fixed - shown} more")

    print(f"\n{fixed} file(s) {'updated' if apply else 'to update'}"
          f"{f' ({drivefixed} via Drive)' if drivefixed else ''}, "
          f"{already} already correct, {norecover} with no recoverable date.")
    if norecover and not use_drive:
        print("Tip: re-run with --drive to recover dates Google Drive knows about.")
    if not apply:
        print("(dry run — re-run with --apply to write the dates)")


if __name__ == "__main__":
    main()
