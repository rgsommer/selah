"""Voice control module for Selah Display System.

Uses SpeechRecognition library with USB microphone.
Commands: next, previous, pause, resume.
"""

import time
from modules.logger import log_error

_last_listen_time = 0
_listen_cooldown = 3

try:
    import speech_recognition as sr
    HAS_SPEECH = True
except ImportError:
    HAS_SPEECH = False


def process_voice_command(screens, config, state, portrait_files, landscape_files):
    """Listen for a voice command and process it. Non-blocking."""
    global _last_listen_time

    if not config.get("voice_control_enabled", False):
        return
    if not HAS_SPEECH:
        return

    now = time.time()
    if now - _last_listen_time < _listen_cooldown:
        return
    _last_listen_time = now

    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True

        with sr.Microphone() as source:
            try:
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=3)
            except sr.WaitTimeoutError:
                return

        try:
            text = recognizer.recognize_google(audio).lower().strip()
        except sr.UnknownValueError:
            return
        except sr.RequestError as e:
            log_error(f"Speech recognition API error: {e}")
            return

        _handle_command(text, screens, config, state, portrait_files, landscape_files)

    except OSError:
        config["voice_control_enabled"] = False
    except Exception as e:
        log_error(f"Voice control error: {e}")


def _handle_command(text, screens, config, state, portrait_files, landscape_files):
    """Map recognized text to actions."""
    from modules.toast import show_toast_if_needed

    command_map = {
        "next": _cmd_next,
        "forward": _cmd_next,
        "skip": _cmd_next,
        "previous": _cmd_previous,
        "back": _cmd_previous,
        "pause": _cmd_pause,
        "stop": _cmd_pause,
        "resume": _cmd_resume,
        "play": _cmd_resume,
        "start": _cmd_resume,
    }

    for keyword, handler in command_map.items():
        if keyword in text:
            handler(screens, config, state, portrait_files, landscape_files)
            show_toast_if_needed(screens, config, f"Voice: {keyword}")
            return


def _cmd_next(screens, config, state, portrait_files, landscape_files):
    for screen_type in ["portrait", "landscape"]:
        if screen_type in state:
            files = portrait_files if screen_type == "portrait" else landscape_files
            if files:
                state[screen_type]["index"] = (state[screen_type]["index"] + 1) % len(files)
                state[screen_type]["paused_until"] = 0


def _cmd_previous(screens, config, state, portrait_files, landscape_files):
    for screen_type in ["portrait", "landscape"]:
        if screen_type in state:
            files = portrait_files if screen_type == "portrait" else landscape_files
            if files:
                state[screen_type]["index"] = (state[screen_type]["index"] - 1) % len(files)
                state[screen_type]["paused_until"] = 0


def _cmd_pause(screens, config, state, portrait_files, landscape_files):
    pause_duration = config.get("manual_navigation_pause", 60) * 10
    for screen_type in state:
        if isinstance(state[screen_type], dict) and "paused_until" in state[screen_type]:
            state[screen_type]["paused_until"] = time.time() + pause_duration


def _cmd_resume(screens, config, state, portrait_files, landscape_files):
    for screen_type in state:
        if isinstance(state[screen_type], dict) and "paused_until" in state[screen_type]:
            state[screen_type]["paused_until"] = 0
