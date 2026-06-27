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


def is_portrait(file_path):
    """Determine if an image is portrait based on dimensions and EXIF orientation.

    Results are cached so each file is only opened once.
    """
    _load_orientation_cache()

    # Check cache first (keyed by absolute path + mtime for invalidation)
    try:
        mtime = os.path.getmtime(file_path)
        cache_key = f"{file_path}|{mtime}"
    except Exception:
        cache_key = file_path

    if cache_key in _orientation_cache:
        return _orientation_cache[cache_key]

    if not HAS_PIL:
        return False
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
            result = height > width
            _orientation_cache[cache_key] = result
            return result
    except Exception:
        _orientation_cache[cache_key] = False
        return False


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
        image_ext = [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]

        def collect_files(folder, forced_list_by_folder=None, orientation=None):
            """Collect media files from a folder.

            If orientation is specified, all files go to forced_list_by_folder.
            Otherwise, detect orientation and sort into portrait/landscape.
            Tracks which immediate subfolder (or root folder) each file belongs to.
            """
            folder_path = Path(folder)
            if not folder_path.exists():
                return
            for path in folder_path.rglob("*"):
                if path.suffix.lower() not in valid_ext:
                    continue
                filepath = str(path)

                # Determine the grouping key: the immediate subfolder under
                # the scanned folder, or the folder itself if file is at root
                relative = path.relative_to(folder_path)
                if len(relative.parts) > 1:
                    group_key = str(folder_path / relative.parts[0])
                else:
                    group_key = str(folder_path)

                if orientation and forced_list_by_folder is not None:
                    forced_list_by_folder.setdefault(group_key, []).append(filepath)
                else:
                    if path.suffix.lower() in image_ext:
                        if is_portrait(filepath):
                            portrait_by_folder.setdefault(group_key, []).append(filepath)
                        else:
                            landscape_by_folder.setdefault(group_key, []).append(filepath)
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

            # Collect dated folders (e.g., media/2025-05-10/)
            media_path = Path(media_folder)
            if media_path.exists():
                for path in media_path.iterdir():
                    if path.is_dir() and len(path.name) == 10 and path.name[4] == '-':
                        collect_files(path, orientation=None)
        else:
            collect_files(media_folder, orientation=None)

        # Balanced shuffle: each folder gets equal airtime
        portrait_files = _balanced_shuffle(portrait_by_folder)
        landscape_files = _balanced_shuffle(landscape_by_folder)

        # Remove duplicates while preserving order
        portrait_files = list(dict.fromkeys(portrait_files))
        landscape_files = list(dict.fromkeys(landscape_files))

        # Persist orientation cache to disk so next startup is fast
        _save_orientation_cache()

        return portrait_files, landscape_files

    except Exception as e:
        log_error(f"Image loading failed: {e}", critical=True, config=config)
        return [], []
