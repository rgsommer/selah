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


_out_state = {}


def output_power(display_id, on, output_name=None):
    """Power a single HDMI output on/off, trying every mechanism that works
    across Raspberry Pi OS graphics stacks:

      - X11 + KMS (the modern default): xrandr --output <name> --off / --auto
        (vcgencmd is a firmware no-op under KMS, so this is the one that
        actually cuts the signal and drops the monitor to standby)
      - Wayland (wlroots): wlr-randr --output <name> --off / --on
      - legacy firmware / fake-KMS: vcgencmd display_power 0/1 <id>

    display_id is the vcgencmd numeric id (Pi 4: HDMI-0 = 2, HDMI-1 = 7);
    output_name is the xrandr connector (e.g. 'HDMI-1'). Idempotent per output."""
    key = output_name if output_name else display_id
    if key is None:
        return
    if _out_state.get(key) == bool(on):
        return
    if output_name:
        # X11 + KMS — the reliable per-connector lever on current Pi OS.
        _run(f"xrandr --output {output_name} --{'auto' if on else 'off'}")
        # Wayland/wlroots uses HDMI-A-1 / HDMI-A-2 style names.
        wlr = "HDMI-A-" + str(output_name).split("-")[-1]
        _run(f"wlr-randr --output {wlr} --{'on' if on else 'off'}")
    if display_id is not None:
        try:
            _run(f"vcgencmd display_power {1 if on else 0} {int(display_id)}")
        except Exception:
            pass
    _out_state[key] = bool(on)
    print(f"[Selah] HDMI {output_name or display_id} -> {'on' if on else 'off'}")


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
