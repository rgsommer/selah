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


def output_power(display_id, on, output_name=None, pos=None):
    """Power a single HDMI output on/off, trying every mechanism that works
    across Raspberry Pi OS graphics stacks:

      - X11 + KMS (the modern default): xrandr --output <name> --off / --auto
        (vcgencmd is a firmware no-op under KMS, so this is the one that
        actually cuts the signal and drops the monitor to standby)
      - Wayland (wlroots): wlr-randr --output <name> --off / --on
      - legacy firmware / fake-KMS: vcgencmd display_power 0/1 <id>

    display_id is the vcgencmd numeric id (Pi 4: HDMI-0 = 2, HDMI-1 = 7);
    output_name is the xrandr connector (e.g. 'HDMI-1'); pos is the connector's
    layout position (e.g. '1920x0') so it's restored in place rather than
    mirrored at 0x0. Idempotent per output."""
    key = output_name if output_name else display_id
    if key is None:
        return
    if _out_state.get(key) == bool(on):
        return
    if output_name:
        # X11 + KMS — the reliable per-connector lever on current Pi OS. On
        # restore, pin the position so it doesn't snap to 0x0 and mirror.
        if on:
            cmd = f"xrandr --output {output_name} --auto"
            if pos:
                cmd += f" --pos {pos}"
            _run(cmd)
        else:
            _run(f"xrandr --output {output_name} --off")
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


def restore_side_by_side(config=None):
    """Assert the canonical side-by-side dual layout, healing a mirrored/overlapped
    state (both outputs stuck at 0x0). Uses --right-of so it needs no width math.
    Safe/no-op on single-monitor or off-Pi setups (xrandr errors are swallowed)."""
    config = config or {}
    s1 = config.get("screen1_output", "HDMI-1")
    s2 = config.get("screen2_output", "HDMI-2")
    _run(f"xrandr --output {s1} --auto --pos 0x0 --primary "
         f"--output {s2} --auto --right-of {s1}")
    _out_state[s1] = True
    _out_state[s2] = True
    print(f"[Selah] Asserted dual layout: {s1} | {s2}")


def prevent_sleep():
    """Stop the OS from blanking/sleeping the screens during the slideshow.

    Disables the X11 screensaver and DPMS (the usual cause on Raspberry Pi OS).
    Best-effort and safe to call repeatedly; no-op where xset isn't present.
    """
    _run("xset s off")        # no screensaver
    _run("xset s noblank")    # don't blank the framebuffer
    _run("xset -dpms")        # no DPMS power-down (sleep)


def keep_display_awake():
    """Daytime safety net: force any DPMS-blanked monitor back on and re-disable
    DPMS, regardless of the tracked on/off state. Harmless when already awake —
    'force on' is a no-op on a live display. Recovers the occasional black screen
    caused by the OS idle-timer blanking despite us thinking the screen is on."""
    _run("xset dpms force on")
    _state["off"] = False
    prevent_sleep()


def screen_off():
    """Put the monitors into standby via DPMS. Layout-safe (does NOT touch the
    xrandr arrangement, so it can never mirror the outputs). Idempotent."""
    if _state["off"]:
        return
    # prevent_sleep() disables DPMS; re-enable it so 'force off' actually blanks.
    _run("xset +dpms")
    _run("xset dpms force off")
    _run("vcgencmd display_power 0")   # legacy fallback; no-op under KMS
    _state["off"] = True
    print("[Selah] Displays to standby (DPMS)")


def screen_on():
    """Wake the monitors from DPMS standby. Layout-safe. Idempotent."""
    if not _state["off"]:
        return
    _run("xset dpms force on")
    _run("vcgencmd display_power 1")
    _state["off"] = False
    # screen_off() re-enabled DPMS so 'force off' would work; leaving it enabled
    # lets the OS idle-timer blank the monitor on its own minutes later (an
    # occasional black screen with no crash). Re-disable it now that we're awake.
    prevent_sleep()
    print("[Selah] Displays woken (DPMS)")
