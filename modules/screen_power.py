"""Power the HDMI output off/on for a true-dark night mode.

A black screen still emits backlight; this actually blanks the display. Tries
several mechanisms so it works across Raspberry Pi OS variants (legacy
broadcom, KMS/Wayland, X11). All are best-effort and no-op off-Pi.
"""

import subprocess

from modules.logger import log_error

_state = {"off": False}


def _run(cmd):
    try:
        subprocess.run(cmd, shell=True, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def is_off():
    return _state["off"]


def prevent_sleep():
    """Stop the OS from blanking/sleeping the screens during the slideshow.

    Disables the X11 screensaver and DPMS (the usual cause on Raspberry Pi OS).
    Best-effort and safe to call repeatedly; no-op where xset isn't present.
    """
    _run("xset s off")        # no screensaver
    _run("xset s noblank")    # don't blank the framebuffer
    _run("xset -dpms")        # no DPMS power-down (sleep)


def screen_off():
    """Blank the HDMI output (no backlight). Idempotent."""
    if _state["off"]:
        return
    # vcgencmd is gentlest (backlight only, keeps the framebuffer); then DPMS.
    _run("vcgencmd display_power 0")
    _run("xset dpms force off")
    _run("wlr-randr --output HDMI-A-1 --off")
    _run("wlr-randr --output HDMI-A-2 --off")
    _state["off"] = True
    print("[Selah] HDMI blanked (night)")


def screen_on():
    """Restore the HDMI output. Idempotent."""
    if not _state["off"]:
        return
    _run("vcgencmd display_power 1")
    _run("xset dpms force on")
    _run("wlr-randr --output HDMI-A-1 --on")
    _run("wlr-randr --output HDMI-A-2 --on")
    _state["off"] = False
    print("[Selah] HDMI restored")
