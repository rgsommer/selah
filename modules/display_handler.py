"""Display initialization and rendering for single or dual HDMI screens.

Key design principles:
  - NEVER crash if a monitor is missing or disconnected
  - Work with 0, 1, or 2 monitors
  - Periodically re-detect monitors so reconnection works without reboot
  - Single monitor shows both portrait and landscape images (auto-scaled)
"""

import os
import time
import subprocess
import pygame
from modules.logger import log_error

try:
    import vlc
    HAS_VLC = True
except ImportError:
    HAS_VLC = False

# Track detected monitors for hot-plug re-detection
_last_monitor_check = 0
_monitor_check_interval = 30  # seconds between re-checks
_known_monitor_count = 0


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


def init_displays():
    """Initialize pygame displays. Returns dict like {'landscape': surface, 'portrait': surface}.

    ALWAYS returns at least one screen if any display is available.
    Returns empty dict only if truly no display can be created.
    Never raises.
    """
    global _known_monitor_count
    screens = {}

    try:
        pygame.init()
        pygame.mouse.set_visible(False)

        monitors = _detect_monitors()
        _known_monitor_count = len(monitors)

        if len(monitors) >= 2:
            print(f"[Selah] {len(monitors)} HDMI displays detected — using dual-screen mode")
            screens = _init_dual_displays(monitors)
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


def _init_dual_displays(monitors):
    """Try to create two separate display windows for dual-screen setup."""
    screens = {}
    try:
        from pygame._sdl2.video import Window
    except ImportError:
        log_error("pygame SDL2 not available for dual display, falling back to single")
        return {}

    windows = []
    for mon in monitors:
        orientation = "portrait" if mon["h"] > mon["w"] else "landscape"
        if orientation in screens:
            orientation = f"{orientation}_2"

        try:
            win = Window(
                f"Selah {orientation}",
                size=(mon["w"], mon["h"]),
                position=(mon["x"], mon["y"]),
                borderless=True,
            )
            surface = win.get_surface()
            screens[orientation] = surface
            windows.append(win)
        except Exception as e:
            log_error(f"Failed to create window for {mon['name']}: {e}")
            # Don't abort — try the next monitor
            continue

    # Store window references so they don't get garbage collected
    if not hasattr(init_displays, '_windows'):
        init_displays._windows = []
    init_displays._windows = windows

    return screens


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

            new_screens = init_displays()
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
        image = pygame.image.load(image_path)
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
        instance = vlc.Instance("--no-xlib")
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

        # Wait for video to finish (with timeout based on rotate_interval * 3)
        max_wait = config.get("rotate_interval", 10) * 3
        start = time.time()
        while player.get_state() not in [vlc.State.Ended, vlc.State.Error]:
            if time.time() - start > max_wait:
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
        if config.get("show_file_date", False) and file_date:
            date_str = file_date if isinstance(file_date, str) else str(file_date)
            items.append(f"{date_str}")
        if config.get("show_file_name", False):
            items.append(os.path.basename(file_path))

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
