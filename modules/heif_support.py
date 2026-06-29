"""Enable HEIC/HEIF (Apple photo) support in PIL.

Importing this module registers the HEIF opener with Pillow, so every PIL
Image.open() in Selah can read .heic/.heif files (display, orientation, and
downscale all go through PIL). No-op if pillow-heif isn't installed — HEICs are
then simply skipped as undecodable rather than crashing.

Install on the Pi with:  pip3 install --break-system-packages pillow-heif
"""

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:
    HEIF_OK = False
