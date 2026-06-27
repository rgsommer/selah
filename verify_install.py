#!/usr/bin/env python3
"""Selah install verifier.

Run this after install (`python3 verify_install.py`) to confirm the Pi has
everything Selah needs before you rely on it. It never changes anything — it
only checks and reports PASS / WARN / FAIL so you can fix issues up front.

Exit code is 0 if there are no hard FAILs, 1 otherwise (handy for scripts).
"""

import importlib
import json
import os
import shutil
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ANSI colors (degrade gracefully if not a TTY)
_TTY = sys.stdout.isatty()
def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s

PASS = _c("32", "PASS")
WARN = _c("33", "WARN")
FAIL = _c("31", "FAIL")

_fail_count = 0
_warn_count = 0


def report(level, label, detail=""):
    global _fail_count, _warn_count
    if level == FAIL:
        _fail_count += 1
    elif level == WARN:
        _warn_count += 1
    line = f"  [{level}] {label}"
    if detail:
        line += f"  — {detail}"
    print(line)


def section(title):
    print("\n" + _c("1", title))


# --- Python packages -------------------------------------------------------
# (import name, pip/apt hint, required?) — some features degrade gracefully.
PACKAGES = [
    ("pygame", "pygame", True),
    ("PIL", "Pillow / python3-pil", True),
    ("requests", "requests / python3-requests", True),
    ("cv2", "python3-opencv", False),          # motion detection
    ("face_recognition", "face_recognition", False),  # face prioritization
    ("speech_recognition", "python3-speechrecognition", False),  # voice
    ("flask", "python3-flask", False),         # web control
    ("bs4", "python3-bs4", False),             # verse scraping
    ("googleapiclient", "google-api-python-client", False),  # calendar/drive
    ("vlc", "python-vlc + vlc", False),        # video playback
    ("RPi.GPIO", "RPi.GPIO (Pi only)", False), # night light
]


def check_packages():
    section("Python packages")
    for mod, hint, required in PACKAGES:
        try:
            importlib.import_module(mod)
            report(PASS, mod)
        except Exception:
            lvl = FAIL if required else WARN
            feature = "" if required else "optional feature will be disabled"
            report(lvl, mod, f"missing — install: {hint}. {feature}".strip())


# --- Files & directories ---------------------------------------------------
REQUIRED_FILES = ["main.py", "display_config.json"]
EXPECTED_DIRS = ["media/portrait", "media/landscape", "media/art", "media/display", "modules"]


def check_files():
    section("Files & directories")
    for f in REQUIRED_FILES:
        report(PASS if os.path.exists(f) else FAIL, f,
                "" if os.path.exists(f) else "missing")
    for d in EXPECTED_DIRS:
        if os.path.isdir(d):
            report(PASS, d + "/")
        else:
            report(WARN, d + "/", "missing — will be created/empty")


# --- Config sanity ---------------------------------------------------------
def check_config():
    section("Configuration")
    path = "display_config.json"
    if not os.path.exists(path):
        report(FAIL, path, "not found")
        return
    try:
        with open(path) as f:
            cfg = json.load(f)
    except Exception as e:
        report(FAIL, path, f"invalid JSON: {e}")
        return
    report(PASS, "display_config.json parses")

    # Effective secrets may come from env / secrets.local.json.
    def effective(key, env):
        return os.environ.get(env) or _secret(key) or cfg.get(key, "")

    email = effective("email_address", "SELAH_EMAIL_ADDRESS")
    pw = effective("email_password", "SELAH_EMAIL_PASSWORD")
    if cfg.get("custom_email_responses") or email:
        report(PASS if email else WARN, "email_address",
                "" if email else "blank — email intake disabled")
        report(PASS if pw else WARN, "email_password",
                "set" if pw else "blank — Gmail intake won't authenticate")

    if cfg.get("weather_enabled"):
        key = effective("weather_api_key", "SELAH_WEATHER_API_KEY")
        ok = key and key != "your_openweathermap_api_key"
        report(PASS if ok else WARN, "weather_api_key",
                "set" if ok else "placeholder — weather will be blank")

    if cfg.get("web_control_enabled"):
        wp = effective("web_control_password", "SELAH_WEB_PASSWORD")
        if wp in ("", "selah123"):
            report(WARN, "web_control_password",
                    "still the default 'selah123' — change it")
        else:
            report(PASS, "web_control_password", "customized")

    # Warn if secrets sit in plaintext while no override is in use.
    if cfg.get("email_password") and not (os.environ.get("SELAH_EMAIL_PASSWORD") or _secret("email_password")):
        report(WARN, "secrets", "password stored plaintext in display_config.json "
                                "— consider secrets.local.json or env vars")


def _secret(key):
    try:
        with open("secrets.local.json") as f:
            return json.load(f).get(key, "")
    except Exception:
        return ""


# --- Hardware (best-effort) ------------------------------------------------
def check_hardware():
    section("Hardware (best-effort)")

    # Camera
    if shutil.which("libcamera-hello") or shutil.which("raspistill"):
        report(PASS, "camera tooling", "libcamera/raspistill present")
    else:
        report(WARN, "camera tooling", "not found — motion/face features need a camera")

    # Microphone
    if shutil.which("arecord"):
        report(PASS, "audio capture (arecord)")
    else:
        report(WARN, "arecord", "not found — voice control needs a mic + ALSA")

    # Displays via xrandr
    if shutil.which("xrandr"):
        try:
            import subprocess
            out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
            n = sum(1 for ln in out.splitlines() if " connected " in ln)
            report(PASS if n else WARN, "displays", f"{n} connected")
        except Exception as e:
            report(WARN, "xrandr", f"query failed: {e}")
    else:
        report(WARN, "xrandr", "not found — single-display fallback will be used")


def main():
    print(_c("1", "Selah Install Verification"))
    check_packages()
    check_files()
    check_config()
    check_hardware()

    print()
    if _fail_count:
        print(_c("31", f"✗ {_fail_count} failure(s), {_warn_count} warning(s). Fix FAILs before running."))
        sys.exit(1)
    elif _warn_count:
        print(_c("33", f"△ Ready, with {_warn_count} warning(s). Some optional features may be off."))
    else:
        print(_c("32", "✓ All checks passed. Selah is ready to run."))
    sys.exit(0)


if __name__ == "__main__":
    main()
