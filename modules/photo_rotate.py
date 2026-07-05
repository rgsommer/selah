"""Permanently rotate a photo file, baking the rotation into the pixels.

Used by F12 to fix a mis-oriented photo: after this the image displays upright
AND re-classifies onto the correct (portrait/landscape) screen, because the
saved file has corrected dimensions and no stale EXIF orientation tag.
"""

import os

import modules.heif_support  # noqa: F401  (register HEIC so .heic can be rotated)
from modules.logger import log_error


def rotate_file(path, angle):
    """Rotate `path` by `angle` degrees counter-clockwise (a multiple of 90) and
    overwrite it. Returns True on success. angle is applied on top of the image's
    current EXIF-corrected orientation, so it matches what's shown on screen."""
    try:
        from PIL import Image, ImageOps
    except Exception as e:
        log_error(f"Rotate needs Pillow: {e}")
        return False
    angle = int(angle) % 360
    if not angle:
        return True
    try:
        with Image.open(path) as im0:
            im = ImageOps.exif_transpose(im0)          # bake existing orientation
            im = im.rotate(angle, expand=True)         # then the user's rotation (CCW)
            im.load()                                  # realize before the file closes

        ext = os.path.splitext(path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            im.convert("RGB").save(path, format="JPEG", quality=92)
        elif ext == ".png":
            im.save(path, format="PNG")
        elif ext in (".heic", ".heif"):
            im.save(path, format="HEIF")               # needs pillow-heif
        else:
            im.save(path)                              # let PIL infer from the name
        return True
    except Exception as e:
        log_error(f"Rotate failed for {path}: {e}")
        return False
