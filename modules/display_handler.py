"""Display initialization and rendering for single or dual HDMI screens.

Key design principles:
  - NEVER crash if a monitor is missing or disconnected
  - Work with 0, 1, or 2 monitors
  - Periodically re-detect monitors so reconnection works without reboot
  - Single monitor shows both portrait and landscape images (auto-scaled)
"""

import os
import re
import time
import random
import datetime
import subprocess
import pygame
from modules.logger import log_error

# Auto-generated / camera filenames that read as junk, not captions.
_GENERIC_NAME_RE = re.compile(
    r"^(photo[-_ ]?\d|img[-_ ]?\d|dsc[nf]?[-_ ]?\d|pxl[-_ ]?\d|vid[-_ ]?\d|"
    r"mvimg|gopr\d|screen[ _-]?shot|screenshot|image([-_ ]?\d|$)|fb[-_]?img|"
    r"whatsapp|signal[-_]|untitled|scan[-_ ]?\d|\d{6,}|[0-9a-f]{12,}$)",
    re.I)


def _is_generic_filename(stem):
    """True if a filename stem looks auto-generated (IMG_1234, photo-1, PXL_...,
    Screenshot, all-digits, hex blob) rather than a meaningful caption."""
    stem = (stem or "").strip()
    if not stem:
        return True
    return bool(_GENERIC_NAME_RE.match(stem))


_photo_date_cache = {}


def _photo_date_str(path):
    """A 'photo date' for the overlay: EXIF capture date if present, else the
    file's modified date, formatted 'Jul 4, 2026'. Cached per file+mtime."""
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = 0
    ck = (path, mtime)
    if ck in _photo_date_cache:
        return _photo_date_cache[ck]
    out = None
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get(306)                      # DateTime
            try:
                sub = ex.get_ifd(0x8769)           # Exif IFD
                raw = sub.get(36867) or sub.get(36868) or raw   # DateTimeOriginal/Digitized
            except Exception:
                pass
        if raw:
            dt = datetime.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
            out = dt.strftime("%b %-d, %Y")
    except Exception:
        out = None
    if not out and mtime:
        try:
            out = datetime.datetime.fromtimestamp(mtime).strftime("%b %-d, %Y")
        except Exception:
            out = None
    _photo_date_cache[ck] = out
    return out

try:
    import vlc
    HAS_VLC = True
except ImportError:
    HAS_VLC = False

# Track detected monitors for hot-plug re-detection
_last_monitor_check = 0
_monitor_check_interval = 30  # seconds between re-checks
_known_monitor_count = 0

# Per-screen record of the photos currently shown and their on-screen rects,
# so the delete flow can number each photo and map a number back to its file.
# Keyed by id(screen surface): {id: [(path, pygame.Rect), ...]}.
_last_photo_rects = {}


def get_photo_rects(screen):
    """The (path, rect) list for the photos currently shown on `screen`."""
    return _last_photo_rects.get(id(screen), [])


def set_photo_rects(screen, rects):
    """Record what's shown on `screen` (used for the full-screen video case)."""
    _last_photo_rects[id(screen)] = rects


def _detect_monitors():
    """Detect connected monitors via xrandr. Returns list of dicts with name, w, h, x, y.

    Never raises — returns empty list on failure.
    """
    monitors = []
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if " connected " in line:
                parts = line.split()
                name = parts[0]
                # Find geometry like 1920x1080+0+0 or 1080x1920+1920+0
                for part in parts:
                    if "x" in part and "+" in part and not part.startswith("("):
                        try:
                            geo = part.split("+")
                            dims = geo[0].split("x")
                            monitors.append({
                                "name": name,
                                "w": int(dims[0]),
                                "h": int(dims[1]),
                                "x": int(geo[1]),
                                "y": int(geo[2]),
                            })
                            break
                        except (ValueError, IndexError):
                            continue
    except FileNotFoundError:
        # xrandr not available (e.g., Wayland-only or no X)
        pass
    except Exception as e:
        log_error(f"xrandr detection failed: {e}")
    return monitors


def init_displays(config=None):
    """Initialize pygame displays. Returns dict like {'landscape': surface, 'portrait': surface}.

    ALWAYS returns at least one screen if any display is available.
    Returns empty dict only if truly no display can be created.
    Never raises.
    """
    global _known_monitor_count
    config = config or {}
    screens = {}

    try:
        pygame.init()
        pygame.mouse.set_visible(False)

        monitors = _detect_monitors()
        _known_monitor_count = len(monitors)

        if len(monitors) >= 2:
            print(f"[Selah] {len(monitors)} HDMI displays detected — using dual-screen mode")
            screens = _init_dual_displays(monitors, config)
        elif len(monitors) == 1:
            print("[Selah] Single HDMI display detected at startup — using it alone")
        else:
            print("[Selah] No HDMI display detected via xrandr — falling back to default display")

        if not screens:
            # Single display fallback — works with 0 or 1 detected monitors.
            # Also reached if dual-init failed, so we degrade to one screen
            # instead of crashing.
            if len(monitors) >= 2:
                print("[Selah] Dual-screen init produced no screens — degrading to single display")
            screens = _init_single_display()

        if screens:
            names = list(screens.keys())
            print(f"[Selah] Displays initialized: {names}")
        else:
            print("[Selah] WARNING: No displays could be initialized")

        return screens

    except Exception as e:
        log_error(f"Display initialization failed: {e}", critical=True)
        return {}


def _init_dual_displays(monitors, config=None):
    """One borderless window spanning all monitors; each monitor is a subsurface.

    This uses the single display surface created by set_mode(), so the normal
    pygame.display.flip() in the render code updates EVERY screen.

    Software rotation: a physically portrait-mounted monitor (which X still
    reports as landscape) can be handled here. We hand the app an upright
    *portrait* logical surface; a flip() hook rotates it onto the real
    (landscape) region. Set software_portrait_screen = "left"/"right" and
    software_rotate_dir = "right"/"left".
    """
    config = config or {}
    screens = {}
    try:
        total_w = max(m["x"] + m["w"] for m in monitors)
        total_h = max(m["y"] + m["h"] for m in monitors)

        os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
        screen = pygame.display.set_mode((total_w, total_h), pygame.NOFRAME)
        pygame.display.set_caption("Selah Display")

        ordered = sorted(monitors, key=lambda m: (m["x"], m["y"]))

        # Which physical screen (if any) is mounted portrait?
        which = (config.get("software_portrait_screen") or "none").lower()
        rotate_dir = (config.get("software_rotate_dir") or "right").lower()
        angle = -90 if rotate_dir == "right" else 90  # pygame rotate is CCW-positive
        target = None
        if which == "right":
            target = ordered[-1]
        elif which == "left":
            target = ordered[0]

        global _rotations
        _rotations = []

        for mon in ordered:
            try:
                phys = screen.subsurface((mon["x"], mon["y"], mon["w"], mon["h"]))
            except ValueError as e:
                log_error(f"Subsurface for {mon.get('name')} out of range: {e}")
                continue

            if target is not None and mon is target:
                # Upright portrait surface (swap dims); rotated onto phys on flip.
                logical = pygame.Surface((mon["h"], mon["w"]))
                screens["portrait"] = logical
                _rotations.append((logical, phys, angle))
                print(f"[Selah] Software-rotating {mon.get('name')} "
                      f"{'90 right' if angle == -90 else '90 left'} (portrait)")
            else:
                orientation = "portrait" if mon["h"] > mon["w"] else "landscape"
                if orientation in screens:
                    orientation = f"{orientation}_2"
                screens[orientation] = phys

        _install_flip_hook()
        return screens

    except Exception as e:
        log_error(f"Dual display init failed: {e}")
        return {}


# --- Software-rotation flip hook -------------------------------------------
_rotations = []          # list of (logical_surface, physical_subsurface, angle)
_flip_hooked = False
_orig_flip = None


def _install_flip_hook():
    """Patch pygame.display.flip so every flip rotates logical surfaces onto
    their physical regions. No-op when nothing needs rotating."""
    global _flip_hooked, _orig_flip
    if _flip_hooked or not _rotations:
        return
    _orig_flip = pygame.display.flip

    def _hooked_flip(*args, **kwargs):
        try:
            for logical, phys, angle in _rotations:
                phys.blit(pygame.transform.rotate(logical, angle), (0, 0))
        except Exception:
            pass
        _orig_flip(*args, **kwargs)

    pygame.display.flip = _hooked_flip
    _flip_hooked = True


def _init_single_display():
    """Initialize a single fullscreen display. Always works if any display exists."""
    screens = {}
    try:
        display_info = pygame.display.Info()
        w, h = display_info.current_w, display_info.current_h

        if w <= 0 or h <= 0:
            # No display detected at all
            log_error("No display dimensions detected")
            return {}

        screen = pygame.display.set_mode((w, h), pygame.FULLSCREEN)
        pygame.display.set_caption("Selah Display")

        # With a single screen, we show both orientations on it
        # Classify by the physical screen orientation
        if h > w:
            screens["portrait"] = screen
        else:
            screens["landscape"] = screen

        return screens

    except Exception as e:
        log_error(f"Single display init failed: {e}")
        return {}


def check_for_display_changes(screens, config):
    """Periodically check if monitors were connected/disconnected.

    Call this from the main loop. Returns updated screens dict if a change
    was detected, or the same dict if no change.
    """
    global _last_monitor_check, _known_monitor_count

    now = time.time()
    if now - _last_monitor_check < _monitor_check_interval:
        return screens

    _last_monitor_check = now

    try:
        monitors = _detect_monitors()
        current_count = len(monitors)

        if current_count != _known_monitor_count:
            print(f"[Selah] Monitor change detected: {_known_monitor_count} -> {current_count}")
            _known_monitor_count = current_count

            # Reinitialize displays
            try:
                pygame.display.quit()
            except Exception:
                pass
            try:
                pygame.display.init()
            except Exception:
                pass

            new_screens = init_displays(config)
            if new_screens:
                return new_screens
            else:
                # Re-init failed — keep using what we had
                log_error("Display re-init failed after monitor change, keeping current setup")
                return screens

    except Exception as e:
        log_error(f"Display change check failed: {e}")

    return screens


def show_image(screen, image_path, config, file_date=None, caption=None):
    """Display an image on the given screen surface with optional metadata overlay."""
    try:
        image = _load_surface(image_path)
        screen_w, screen_h = screen.get_size()

        # Scale preserving aspect ratio, then center
        img_w, img_h = image.get_size()
        if img_w == 0 or img_h == 0:
            return
        scale = min(screen_w / img_w, screen_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        image = pygame.transform.smoothscale(image, (new_w, new_h))

        # Black background then centered image
        screen.fill((0, 0, 0))
        x_offset = (screen_w - new_w) // 2
        y_offset = (screen_h - new_h) // 2
        screen.blit(image, (x_offset, y_offset))

        # Theme border if active
        try:
            from modules.theme_manager import draw_theme_border
            draw_theme_border(screen)
        except Exception:
            pass

        # Metadata overlay
        _draw_overlay(screen, image_path, config, file_date, caption)

        try:
            pygame.display.flip()
        except Exception:
            pass

    except pygame.error as e:
        log_error(f"Image display failed for {image_path}: {e}")
    except Exception as e:
        log_error(f"Image display failed for {image_path}: {e}")


def show_video(screen, video_path, config, file_date=None, caption=None):
    """Play a video on the given screen using VLC."""
    if not HAS_VLC:
        log_error("VLC not available, skipping video playback")
        return
    try:
        args = ["--no-xlib"]
        if config.get("video_muted", True):
            args.append("--no-audio")     # quiet frame by default
        instance = vlc.Instance(*args)
        player = instance.media_player_new()
        media = instance.media_new(video_path)
        player.set_media(media)

        # Try to get the window handle for embedding
        try:
            wm_info = pygame.display.get_wm_info()
            if "window" in wm_info:
                player.set_xwindow(wm_info["window"])
        except Exception:
            pass

        player.play()

        # Draw metadata overlay
        _draw_overlay(screen, video_path, config, file_date, caption)

        # Play until the video ends, or up to video_max_seconds (0 = play full).
        max_wait = config.get("video_max_seconds", 60)
        start = time.time()
        while player.get_state() not in [vlc.State.Ended, vlc.State.Error]:
            if max_wait and time.time() - start > max_wait:
                break
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    player.stop()
                    return
            time.sleep(0.5)
        player.stop()
    except Exception as e:
        log_error(f"Video display failed for {video_path}: {e}", config=config)


def _draw_overlay(screen, file_path, config, file_date=None, caption=None):
    """Draw metadata text overlay at the bottom of the screen."""
    try:
        font_size = max(24, screen.get_height() // 30)
        font = pygame.font.Font(None, font_size)
        y_offset = screen.get_height() - 30
        padding = 10

        items = []
        if config.get("show_caption", False) and caption:
            items.append(f"{caption}")
        if config.get("show_file_date", False):
            # Prefer the known media date; otherwise derive from EXIF / file date.
            date_str = ((file_date if isinstance(file_date, str) else str(file_date))
                        if file_date else _photo_date_str(file_path))
            if date_str:
                items.append(date_str)
        if config.get("show_file_name", True):
            stem = os.path.splitext(os.path.basename(file_path))[0]
            # Skip auto-generated names (IMG_1234 etc.); show meaningful ones
            # (which the user uses as captions) — without the extension.
            if not (config.get("hide_generic_filenames", True) and _is_generic_filename(stem)):
                items.append(stem)

        # Draw from bottom up with semi-transparent background
        for text_str in items:
            text_surface = font.render(text_str, True, (255, 255, 255))
            text_rect = text_surface.get_rect()
            text_rect.bottomleft = (padding, y_offset)

            # Semi-transparent background box
            bg_rect = text_rect.inflate(16, 8)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            bg_surface.fill((0, 0, 0, 160))
            screen.blit(bg_surface, bg_rect.topleft)
            screen.blit(text_surface, text_rect)
            y_offset -= text_rect.height + 8

    except Exception as e:
        log_error(f"Overlay draw failed: {e}")


# ---------------------------------------------------------------------------
# Layout variety — full single / tile-3 / tile-6 with crossfade transitions
# ---------------------------------------------------------------------------

_LAYOUT_COUNTS = {"single": 1, "split": 2, "cascade": 3, "tile3": 3, "tile6": 6}


def layout_file_count(mode):
    """How many images a layout mode consumes."""
    return _LAYOUT_COUNTS.get(mode, 1)


def pick_layout_mode(config):
    """Randomly choose a layout for this rotation, weighted by config.

    Returns 'single' when variety is disabled. Weights default to mostly-single
    so the display stays calm, with occasional collages for interest.
    """
    if not config.get("layout_variety_enabled", True):
        return "single"
    weights = config.get("layout_weights", {"single": 50, "tile3": 30, "tile6": 20})
    modes = [m for m in weights if weights.get(m, 0) > 0] or ["single"]
    try:
        return random.choices(modes, weights=[weights[m] for m in modes], k=1)[0]
    except Exception:
        return "single"


import modules.heif_support  # noqa: F401  (registers HEIC/HEIF with PIL)


def _load_surface(image_path):
    """Load an image as a pygame Surface, honoring EXIF orientation.

    pygame.image.load ignores EXIF, so phone/camera photos with a rotation tag
    show sideways AND mismatch how is_portrait classified them (landing on the
    wrong screen). Going through PIL's exif_transpose makes display match
    classification.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:
        return pygame.image.load(image_path)
    try:
        with Image.open(image_path) as im:
            # Decode JPEGs at reduced resolution up front so a giant scan never
            # allocates the full bitmap (~585MB for 195MP) on the Pi. Perf only —
            # its failure must NOT skip the rotation step below.
            try:
                im.draft("RGB", (4000, 4000))
            except Exception:
                pass
            # Rotation is critical: isolate it so a later convert/thumbnail hiccup
            # can't send us to the unrotated pygame fallback.
            try:
                im = ImageOps.exif_transpose(im)
            except Exception as e:
                log_error(f"exif_transpose failed for {os.path.basename(image_path)}: {e}")
            im = im.convert("RGB")
            if max(im.size) > 4000:
                im.thumbnail((4000, 4000), Image.LANCZOS)
            return pygame.image.fromstring(im.tobytes(), im.size, "RGB")
    except Exception as e:
        # Last resort: pygame.image.load ignores EXIF, so this photo may show
        # sideways. Log it so mis-rotated files can be identified.
        log_error(f"PIL load failed (may show unrotated): {os.path.basename(image_path)}: {e}")
        try:
            return pygame.image.load(image_path)
        except Exception:
            return None


def _scaled_image(image_path, max_w, max_h):
    """Load and aspect-scale an image to fit within (max_w, max_h)."""
    image = _load_surface(image_path)
    iw, ih = image.get_size()
    if iw == 0 or ih == 0:
        return None
    scale = min(max_w / iw, max_h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    return pygame.transform.smoothscale(image, (nw, nh))


def _apply_effect(surf, effect):
    """Return a sepia or black & white version of a surface (best-effort)."""
    if not hasattr(pygame.transform, "grayscale"):
        return surf  # older pygame without grayscale — skip gracefully
    try:
        gray = pygame.transform.grayscale(surf)
        if effect == "bw":
            return gray
        if effect == "sepia":
            tint = gray.copy()
            # Multiply the gray image by a warm tone -> sepia.
            tint.fill((255, 204, 153), special_flags=pygame.BLEND_RGB_MULT)
            return tint
    except Exception:
        pass
    return surf


def _is_recent_submission(path, config):
    """True if a photo was added within the feature window — keep it true colour."""
    if not path or not config.get("feature_new_enabled", True):
        return False
    days = int(config.get("feature_new_days", 3) or 0)
    if days <= 0:
        return False
    try:
        return (time.time() - os.path.getmtime(path)) / 86400.0 <= days
    except Exception:
        return False


def _maybe_effect(surf, config, path=None):
    """Randomly apply sepia/B&W to a photo, per the configured chance — but never
    to a newly-submitted photo while it's being featured (keep it true colour)."""
    if surf is None or not config.get("photo_effects_enabled", False):
        return surf
    if _is_recent_submission(path, config):
        return surf
    try:
        if random.randint(1, 100) <= int(config.get("photo_effect_chance", 15)):
            choices = []
            if config.get("photo_effect_sepia", True):
                choices.append("sepia")
            if config.get("photo_effect_bw", True):
                choices.append("bw")
            if choices:
                return _apply_effect(surf, random.choice(choices))
    except Exception:
        pass
    return surf


def _build_single_frame(screen, image_path, config, file_date, caption):
    """Render one centered photo (with overlay/theme) onto an offscreen frame.
    Returns (frame, rects) where rects is [(path, pygame.Rect), ...]."""
    w, h = screen.get_size()
    frame = pygame.Surface((w, h))
    frame.fill((0, 0, 0))
    rects = []
    img = _scaled_image(image_path, w, h)
    if img:
        img = _maybe_effect(img, config, image_path)
        iw, ih = img.get_size()
        x, y = (w - iw) // 2, (h - ih) // 2
        frame.blit(img, (x, y))
        rects.append((image_path, pygame.Rect(x, y, iw, ih)))
    try:
        from modules.theme_manager import draw_theme_border
        draw_theme_border(frame)
    except Exception:
        pass
    _draw_overlay(frame, image_path, config, file_date, caption)
    return frame, rects


def _gutter_px(config, w):
    """Width of the separating line between photos in multi layouts.

    Defaults to ~0.5 cm on a typical HDMI panel (~width/110). Override with
    multi_gutter_px in the config for an exact pixel width.
    """
    g = config.get("multi_gutter_px", 0)
    if g and int(g) > 0:
        return int(g)
    return max(6, round(w / 110))


def _build_grid_frame(screen, paths, cols, rows, config):
    """Render a cols x rows photo collage. Returns (frame, rects)."""
    w, h = screen.get_size()
    frame = pygame.Surface((w, h))
    frame.fill((0, 0, 0))
    gap = _gutter_px(config, w)
    cell_w = (w - gap * (cols + 1)) // cols
    cell_h = (h - gap * (rows + 1)) // rows

    rects = []
    n = 0
    for r in range(rows):
        for c in range(cols):
            if n >= len(paths):
                break
            cx = gap + c * (cell_w + gap)
            cy = gap + r * (cell_h + gap)
            try:
                img = _scaled_image(paths[n], cell_w, cell_h)
                if img:
                    img = _maybe_effect(img, config, paths[n])
                    iw, ih = img.get_size()
                    x, y = cx + (cell_w - iw) // 2, cy + (cell_h - ih) // 2
                    frame.blit(img, (x, y))
                    rects.append((paths[n], pygame.Rect(x, y, iw, ih)))
            except Exception as e:
                log_error(f"Tile render failed for {paths[n]}: {e}")
            n += 1

    try:
        from modules.theme_manager import draw_theme_border
        draw_theme_border(frame)
    except Exception:
        pass
    return frame, rects


def _build_split_frame(screen, paths, config):
    """Two photos, each ~50%. Side by side on a landscape screen; on a portrait
    screen, stacked one above the other, the two photos separated by only
    ~split_portrait_gap of their height and the lower one shifted sideways by
    split_portrait_offset (default 20%). Returns (frame, rects)."""
    w, h = screen.get_size()
    frame = pygame.Surface((w, h))
    frame.fill((0, 0, 0))
    gap = _gutter_px(config, w)
    rects = []

    if h > w and len(paths) >= 2:
        off = int(w * float(config.get("split_portrait_offset", 0.2)))
        cw = w - off
        per_h = int(h * 0.44)                       # each photo up to ~44% of height
        imgs = []
        for p in paths[:2]:
            try:
                im = _scaled_image(p, cw, per_h)
                if im:
                    im = _maybe_effect(im, config, p)
            except Exception as e:
                log_error(f"Split render failed for {p}: {e}")
                im = None
            imgs.append(im)
        if imgs[0] and imgs[1]:
            h1, h2 = imgs[0].get_height(), imgs[1].get_height()
            frac = float(config.get("split_portrait_gap", 0.10))
            sep = int(frac * (h1 + h2) / 2)         # gap = ~10% of photo height
            total = h1 + sep + h2
            offy = max(gap, (h - total) // 2)
            pos = [((cw - imgs[0].get_width()) // 2, offy),
                   (off + (cw - imgs[1].get_width()) // 2, offy + h1 + sep)]
            for idx, im in enumerate(imgs):
                x, y = pos[idx]
                frame.blit(im, (x, y))
                rects.append((paths[idx], pygame.Rect(x, y, im.get_width(), im.get_height())))
        else:  # a photo failed to load — center whichever we have
            im = imgs[0] or imgs[1]
            p = paths[0] if imgs[0] else paths[1]
            if im:
                x, y = (w - im.get_width()) // 2, (h - im.get_height()) // 2
                frame.blit(im, (x, y))
                rects.append((p, pygame.Rect(x, y, im.get_width(), im.get_height())))
    else:
        cell_w = (w - gap) // 2
        cells = [(0, 0, cell_w, h), (cell_w + gap, 0, w - cell_w - gap, h)]
        for idx, (cx, cy, cwid, ch) in enumerate(cells):
            if idx >= len(paths):
                break
            try:
                img = _scaled_image(paths[idx], cwid, ch)
                if img:
                    img = _maybe_effect(img, config, paths[idx])
                    iw, ih = img.get_size()
                    x, y = cx + (cwid - iw) // 2, cy + (ch - ih) // 2
                    frame.blit(img, (x, y))
                    rects.append((paths[idx], pygame.Rect(x, y, iw, ih)))
            except Exception as e:
                log_error(f"Split render failed for {paths[idx]}: {e}")

    try:
        from modules.theme_manager import draw_theme_border
        draw_theme_border(frame)
    except Exception:
        pass
    return frame, rects


def _build_cascade_frame(screen, paths, config):
    """3 photos cascading diagonally top-left -> centre -> bottom-right, each
    overlapping the next by ~cascade_overlap and sized by cascade_size (fraction
    of the screen). Later photos stack on top, and the outer two bleed a little
    off the corners so the photos can be large."""
    w, h = screen.get_size()
    frame = pygame.Surface((w, h))
    frame.fill((16, 16, 22))
    size = float(config.get("cascade_size", 0.5))
    ov = float(config.get("cascade_overlap", 0.10))
    cell_w, cell_h = int(w * size), int(h * size)
    border = max(4, w // 220)

    imgs = []
    used_paths = []
    for p in paths[:3]:
        try:
            im = _scaled_image(p, cell_w, cell_h)
            if im:
                imgs.append(_maybe_effect(im, config, p))
                used_paths.append(p)
        except Exception as e:
            log_error(f"Cascade render failed for {p}: {e}")
    if not imgs:
        return frame, []

    # Cascade each photo down-right from the previous, overlapping its corner by
    # `ov` of the *actual* photo size, then centre the whole stack.
    xs, ys = [0], [0]
    for k in range(1, len(imgs)):
        pw, ph = imgs[k - 1].get_size()
        xs.append(xs[-1] + int(pw * (1 - ov)))
        ys.append(ys[-1] + int(ph * (1 - ov)))
    total_w = max(xs[k] + imgs[k].get_width() for k in range(len(imgs)))
    total_h = max(ys[k] + imgs[k].get_height() for k in range(len(imgs)))

    # Clamp: scale the whole stack (white borders included) to fit inside a
    # safe-area margin, so it clears the white borders AND TV overscan, which
    # crops the outer few %. Overlap proportions are preserved.
    margin = max(border * 2, int(h * 0.05))           # ~5% safe area
    avail_w, avail_h = w - 2 * margin, h - 2 * margin
    fit = min(1.0, avail_w / (total_w + 2 * border), avail_h / (total_h + 2 * border))
    if fit < 1.0:
        imgs = [pygame.transform.smoothscale(
                    im, (max(1, int(im.get_width() * fit)),
                         max(1, int(im.get_height() * fit)))) for im in imgs]
        xs = [int(x * fit) for x in xs]
        ys = [int(y * fit) for y in ys]
        total_w = max(xs[k] + imgs[k].get_width() for k in range(len(imgs)))
        total_h = max(ys[k] + imgs[k].get_height() for k in range(len(imgs)))
    offx, offy = (w - total_w) // 2, (h - total_h) // 2

    rects = []
    for k in range(len(imgs)):
        iw, ih = imgs[k].get_size()
        x, y = xs[k] + offx, ys[k] + offy
        pygame.draw.rect(frame, (240, 240, 240),
                         (x - border, y - border, iw + 2 * border, ih + 2 * border))
        frame.blit(imgs[k], (x, y))
        rects.append((used_paths[k], pygame.Rect(x, y, iw, ih)))
    try:
        from modules.theme_manager import draw_theme_border
        draw_theme_border(frame)
    except Exception:
        pass
    return frame, rects


def _stamp(screen, overlay):
    """Re-blit the persistent band overlay (if any) on top of the current frame."""
    if overlay is not None:
        screen.blit(overlay, (0, 0))


def _present_split(screen, new_frame, animate=True, overlay=None):
    """Transition for split mode: the two old halves slide off opposite ways,
    revealing the new split underneath."""
    try:
        if animate:
            w, h = screen.get_size()
            half = w // 2
            old = screen.copy()
            left = old.subsurface((0, 0, half, h)).copy()
            right = old.subsurface((half, 0, w - half, h)).copy()
            step = max(2, half // 14)
            dx = 0
            while dx < half:
                screen.blit(new_frame, (0, 0))
                screen.blit(left, (-dx, 0))           # left half exits left
                screen.blit(right, (half + dx, 0))    # right half exits right
                _stamp(screen, overlay)
                pygame.display.flip()
                pygame.time.delay(16)
                dx += step
        screen.blit(new_frame, (0, 0))
        _stamp(screen, overlay)
        pygame.display.flip()
    except Exception as e:
        log_error(f"Split transition failed: {e}")


def _pick_transition(config):
    """Which transition to use: crossfade, fade_black, or a random one."""
    ts = (config.get("transition_style") or "crossfade").lower()
    if ts == "random":
        return random.choice(["crossfade", "fade_black"])
    return ts


def _fade_through_black(screen, frame, overlay=None):
    """Fade the current frame down to black, then fade the new one up.

    The persistent band overlay (if any) stays fully visible on top throughout,
    so the photo dips to black but the time/weather band never blanks out."""
    try:
        w, h = screen.get_size()
        old = screen.copy()
        black = pygame.Surface((w, h))
        black.fill((0, 0, 0))
        for a in range(0, 256, 30):          # old -> black
            screen.blit(old, (0, 0))
            black.set_alpha(a)
            screen.blit(black, (0, 0))
            _stamp(screen, overlay)
            pygame.display.flip()
            pygame.time.delay(14)
        for a in range(0, 256, 30):          # black -> new
            screen.fill((0, 0, 0))
            frame.set_alpha(a)
            screen.blit(frame, (0, 0))
            _stamp(screen, overlay)
            pygame.display.flip()
            pygame.time.delay(14)
        frame.set_alpha(255)
        screen.blit(frame, (0, 0))
        _stamp(screen, overlay)
        pygame.display.flip()
    except Exception as e:
        log_error(f"Fade-through-black failed: {e}")


def _present(screen, frame, fade=True, style="crossfade", overlay=None):
    """Blit a finished frame to the screen, with the chosen transition.

    overlay (a per-pixel-alpha surface) is re-stamped on top of every animation
    frame so it stays put through the transition instead of blanking out."""
    try:
        if fade and style == "fade_black":
            _fade_through_black(screen, frame, overlay)
            return
        if fade:  # crossfade
            old = screen.copy()
            for alpha in range(0, 256, 28):
                frame.set_alpha(alpha)
                screen.blit(old, (0, 0))
                screen.blit(frame, (0, 0))
                _stamp(screen, overlay)
                pygame.display.flip()
                pygame.time.delay(16)
            frame.set_alpha(255)
        screen.blit(frame, (0, 0))
        _stamp(screen, overlay)
        pygame.display.flip()
    except Exception as e:
        log_error(f"Frame present failed: {e}")


def show_layout(screen, image_paths, config, mode, file_meta=None, fade=True, overlay=None):
    """Render a layout (single / tile3 / tile6) with an optional crossfade.

    image_paths must hold enough images for the mode; the caller guarantees
    this and falls back to 'single' otherwise. file_meta=(date, caption) is
    only used in single mode. overlay is a persistent band re-stamped on top of
    every transition frame so it never blanks out.
    """
    try:
        w, h = screen.get_size()
        portrait = h > w

        if mode == "split":
            frame, rects = _build_split_frame(screen, image_paths, config)
            _last_photo_rects[id(screen)] = rects
            _present_split(screen, frame,
                           animate=fade and config.get("layout_fade_enabled", True),
                           overlay=overlay)
            return
        elif mode == "cascade":
            frame, rects = _build_cascade_frame(screen, image_paths, config)
        elif mode == "tile3":
            cols, rows = (1, 3) if portrait else (3, 1)
            frame, rects = _build_grid_frame(screen, image_paths, cols, rows, config)
        elif mode == "tile6":
            cols, rows = (2, 3) if portrait else (3, 2)
            frame, rects = _build_grid_frame(screen, image_paths, cols, rows, config)
        else:
            date, cap = file_meta or (None, None)
            frame, rects = _build_single_frame(screen, image_paths[0], config, date, cap)

        _last_photo_rects[id(screen)] = rects
        _present(screen, frame, fade=fade and config.get("layout_fade_enabled", True),
                 style=_pick_transition(config), overlay=overlay)
    except Exception as e:
        log_error(f"show_layout failed ({mode}): {e}")
