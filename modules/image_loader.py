"""Media file discovery with portrait/landscape orientation detection.

Uses folder-balanced shuffling so that folders with fewer photos get
equal representation compared to folders with many photos.

Orientation results are cached to disk (orientation_cache.json) so the
expensive PIL open-and-read-EXIF pass only happens once per file.
"""

import os
import json
import random
from pathlib import Path
from modules.logger import log_error
import modules.heif_support  # noqa: F401  (registers HEIC/HEIF with PIL)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

ORIENTATION_CACHE_FILE = "orientation_cache.json"
_orientation_cache = None  # lazy-loaded dict: filepath -> bool (True = portrait)


def _load_orientation_cache():
    """Load the on-disk orientation cache (once per process)."""
    global _orientation_cache
    if _orientation_cache is not None:
        return
    try:
        with open(ORIENTATION_CACHE_FILE, "r") as f:
            _orientation_cache = json.load(f)
    except Exception:
        _orientation_cache = {}


def _save_orientation_cache():
    """Persist orientation cache to disk."""
    if _orientation_cache is None:
        return
    try:
        with open(ORIENTATION_CACHE_FILE, "w") as f:
            json.dump(_orientation_cache, f)
    except Exception as e:
        log_error(f"Failed to save orientation cache: {e}")


def photo_dims(file_path):
    """Return (is_portrait, long_edge_px) for an image, cached per file.

    long_edge_px == 0 means the file couldn't be decoded (corrupt, or e.g. a
    HEIC misnamed .jpg); -1 means unknown (legacy cache / no PIL).
    """
    _load_orientation_cache()

    # Check cache first (keyed by absolute path + mtime for invalidation)
    try:
        mtime = os.path.getmtime(file_path)
        cache_key = f"{file_path}|{mtime}"
    except Exception:
        cache_key = file_path

    cached = _orientation_cache.get(cache_key)
    if isinstance(cached, list) and len(cached) == 2:
        return bool(cached[0]), int(cached[1])
    if isinstance(cached, bool):          # legacy cache: portrait only
        return cached, -1

    if not HAS_PIL:
        _orientation_cache[cache_key] = [False, -1]
        return False, -1
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            # Check EXIF orientation tag for rotated photos
            try:
                exif = img._getexif()
                if exif:
                    orientation = exif.get(274, 1)  # 274 = Orientation tag
                    if orientation in (6, 8):  # Rotated 90 or 270 degrees
                        width, height = height, width
            except (AttributeError, Exception):
                pass
            portrait = height > width
            long_edge = max(width, height)
            _orientation_cache[cache_key] = [portrait, long_edge]
            return portrait, long_edge
    except Exception:
        _orientation_cache[cache_key] = [False, 0]   # 0 = unreadable
        return False, 0


def is_portrait(file_path):
    """True if an image is portrait (cached)."""
    return photo_dims(file_path)[0]


def _balanced_shuffle(files_by_folder):
    """Shuffle files so each folder gets equal representation.

    Instead of one flat shuffle (which over-represents large folders),
    this round-robins across folders: pick one random file from each
    folder in turn, repeating until all files are placed.
    """
    if not files_by_folder:
        return []

    # Shuffle each folder's files internally
    buckets = []
    for folder, files in files_by_folder.items():
        shuffled = list(files)
        random.shuffle(shuffled)
        if shuffled:
            buckets.append(shuffled)

    if not buckets:
        return []

    # Shuffle the order of the buckets themselves
    random.shuffle(buckets)

    # Round-robin across buckets
    result = []
    while buckets:
        next_round = []
        for bucket in buckets:
            result.append(bucket.pop(0))
            if bucket:
                next_round.append(bucket)
        buckets = next_round

    return result


def get_images_and_videos(config):
    """Scan media directories and return (portrait_files, landscape_files) lists.

    Files are balanced across folders so no single folder dominates the playlist.
    """
    try:
        # Track files per folder for balanced shuffling
        portrait_by_folder = {}
        landscape_by_folder = {}
        valid_ext = [ext.lower() for ext in config.get("valid_extensions",
                     [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"])]
        image_ext = [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic", ".heif"]

        # Guest/privacy mode: when on, hide files under any "private" folder.
        privacy_on = config.get("privacy_mode_enabled", False)
        private_tokens = [str(t).lower() for t in config.get("private_dirs", ["private"])]
        # Skip junk images: undecodable files (corrupt / misnamed HEIC) and
        # anything below min_photo_px on the long edge (placeholder/icon
        # graphics like Drive's generic "?" file). 0 disables the size check.
        min_px = int(config.get("min_photo_px", 0) or 0)

        def collect_files(folder, forced_list_by_folder=None, orientation=None, deep_group=False):
            """Collect media files from a folder.

            If orientation is specified, all files go to forced_list_by_folder.
            Otherwise, detect orientation and sort into portrait/landscape.
            Grouping key is the immediate subfolder by default; with deep_group
            it's the file's full directory, so a big nested folder is split into
            many buckets and gets proportional airtime in balanced rotation.
            """
            folder_path = Path(folder)
            if not folder_path.exists():
                return
            for path in folder_path.rglob("*"):
                if path.suffix.lower() not in valid_ext:
                    continue
                filepath = str(path)

                # Skip private content while guest/privacy mode is on.
                if privacy_on and any(tok in filepath.lower() for tok in private_tokens):
                    continue

                # Determine the grouping key.
                relative = path.relative_to(folder_path)
                if len(relative.parts) <= 1:
                    group_key = str(folder_path)
                elif deep_group:
                    group_key = str(path.parent)              # full leaf directory
                else:
                    group_key = str(folder_path / relative.parts[0])  # immediate subfolder

                is_img = path.suffix.lower() in image_ext
                if is_img:
                    portrait, edge = photo_dims(filepath)
                    if edge == 0:                       # corrupt / undecodable
                        continue
                    if min_px and 0 < edge < min_px:    # placeholder / icon
                        continue

                if orientation and forced_list_by_folder is not None:
                    forced_list_by_folder.setdefault(group_key, []).append(filepath)
                elif is_img:
                    bucket = portrait_by_folder if portrait else landscape_by_folder
                    bucket.setdefault(group_key, []).append(filepath)
                else:
                    # Videos go to both lists
                    portrait_by_folder.setdefault(group_key, []).append(filepath)
                    landscape_by_folder.setdefault(group_key, []).append(filepath)

        media_folder = config.get("media_folder", "media")

        if config.get("media_mode") == "separate":
            portrait_dir = config.get("portrait_dir", "media/portrait")
            landscape_dir = config.get("landscape_dir", "media/landscape")
            art_dir = config.get("art_dir", "media/art")
            display_dir = config.get("display_dir", "media/display")

            collect_files(portrait_dir, portrait_by_folder, orientation="portrait")
            collect_files(landscape_dir, landscape_by_folder, orientation="landscape")
            collect_files(art_dir, orientation=None)
            collect_files(display_dir, orientation=None)

            # Drive-pulled photos (media/shared_drive). Scan it unless it's
            # nested inside a folder already scanned recursively above, which
            # would double the files in the rotation.
            drive_pull_dir = config.get("drive_pull_dir", "media/shared_drive")
            dp_abs = os.path.abspath(drive_pull_dir)
            already = any(
                dp_abs == os.path.abspath(s) or dp_abs.startswith(os.path.abspath(s) + os.sep)
                for s in (portrait_dir, landscape_dir, art_dir, display_dir)
            )
            if not already:
                # Deep-group so big Drive folders (e.g. Family/) get airtime in
                # proportion to their size instead of one slot for the whole tree.
                collect_files(drive_pull_dir, orientation=None,
                              deep_group=config.get("shared_drive_granular", True))

            # Collect dated folders (e.g., media/2025-05-10/)
            media_path = Path(media_folder)
            if media_path.exists():
                for path in media_path.iterdir():
                    if path.is_dir() and len(path.name) == 10 and path.name[4] == '-':
                        collect_files(path, orientation=None)

            # Family/Friends folder — kept separate from personal folders, only
            # mixed into the rotation when the source is enabled.
            if config.get("family_folder_enabled", False):
                collect_files("media/family", orientation=None)
        else:
            collect_files(media_folder, orientation=None)

        # Balanced shuffle: each folder gets equal airtime
        portrait_files = _balanced_shuffle(portrait_by_folder)
        landscape_files = _balanced_shuffle(landscape_by_folder)

        # Remove duplicates while preserving order
        portrait_files = list(dict.fromkeys(portrait_files))
        landscape_files = list(dict.fromkeys(landscape_files))

        # Optionally drop out-of-focus photos (cached; no-op unless enabled).
        try:
            from modules import quality
            portrait_files = quality.filter_sharp(portrait_files, config)
            landscape_files = quality.filter_sharp(landscape_files, config)
        except Exception as e:
            log_error(f"Blur filter failed: {e}")

        # Dated greetings only show on their day, so keep them out of the
        # everyday rotation.
        try:
            from modules.scheduled_media import scheduled_paths
            sched = scheduled_paths()
            if sched:
                portrait_files = [f for f in portrait_files if f not in sched]
                landscape_files = [f for f in landscape_files if f not in sched]
        except Exception:
            pass

        # Persist orientation cache to disk so next startup is fast
        _save_orientation_cache()

        return portrait_files, landscape_files

    except Exception as e:
        log_error(f"Image loading failed: {e}", critical=True, config=config)
        return [], []
