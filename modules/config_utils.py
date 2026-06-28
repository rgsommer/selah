"""Configuration loading and saving utilities."""

import json
import os
from modules.logger import log_error

DEFAULT_CONFIG = {
    "media_mode": "separate",
    "media_folder": "media",
    "portrait_dir": "media/portrait",
    "landscape_dir": "media/landscape",
    "art_dir": "media/art",
    "display_dir": "media/display",
    "valid_extensions": [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"],
    "rotate_interval": 10,
    "manual_navigation_pause": 60,
    "layout_variety_enabled": True,
    "layout_fade_enabled": True,
    "transition_style": "random",
    "layout_weights": {"single": 50, "split": 20, "cascade": 20, "tile3": 30, "tile6": 20},
    "multi_gutter_px": 0,
    "photo_effects_enabled": False,
    "photo_effect_chance": 15,
    "photo_effect_sepia": True,
    "photo_effect_bw": True,
    "recent_memory_enabled": True,
    "recent_memory": 0,
    "balanced_rotation": True,
    "screen_rotation_sync": True,
    "on_this_day_enabled": True,
    "upload_qr_enabled": False,
    "upload_qr_interval_minutes": 30,
    "upload_qr_seconds": 20,
    "qr_upload_url": "",
    "web_control_port": 5000,
    "coming_up_enabled": False,
    "coming_up_interval_minutes": 20,
    "coming_up_seconds": 15,
    "favorites_boost_enabled": True,
    "privacy_mode_enabled": False,
    "private_dirs": ["private"],
    "hide_blurry_enabled": False,
    "blur_threshold": 60,
    "health_watchdog_enabled": True,
    "disk_warn_percent": 10,
    "weekly_digest_enabled": False,
    "weekly_digest_weekday": 6,
    "on_time": "06:00",
    "off_time": "22:00",
    "timezone": "America/Toronto",
    "calendar_start_time": "06:00",
    "calendar_times": [],
    "calendar_duration_minutes": 0,
    "google_calendar_id": "primary",
    "moon_phase_enabled": True,
    "night_screen_off": False,
    "prevent_screen_sleep": True,
    "software_portrait_screen": "none",
    "software_rotate_dir": "right",
    "enable_face_recognition": False,
    "verse_display_enabled": False,
    "calendar_display_enabled": False,
    "email_address": "",
    "email_password": "",
    "imap_server": "imap.gmail.com",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "motion_detection_enabled": False,
    "motion_triggered_slideshow": False,
    "motion_timeout": 300,
    "cloud_backup_enabled": False,
    "google_drive_folder_id": "",
    "google_drive_folder_ids": [],
    "google_drive_backup_folder_id": "",
    "drive_push_enabled": False,
    "drive_upload_batch": 200,
    "drive_downscale_enabled": True,
    "drive_downscale_max_px": 2560,
    "drive_mirror_structure": True,
    "family_folder_enabled": False,
    "family_folder_id": "",
    "family_folder_recurring": True,
    "weather_enabled": False,
    "weather_api_key": "",
    "status_line_enabled": False,
    "status_line_position": "top",
    "status_line_weather": False,
    "new_photo_hint_seconds": 90,
    "overlay_band_persist": True,
    "overlay_fade_in_enabled": True,
    "overlay_fade_seconds": 2.5,
    "weather_pill_enabled": True,
    "weather_pill_position": "top-right",
    "location": "Hamilton,CA",
    "voice_control_enabled": False,
    "web_control_enabled": False,
    "web_control_password": "selah123",
    "theme_enabled": False,
    "pending_badge_enabled": True,
    "notification_sound_enabled": True,
    "notification_sound_path": "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
    "notification_duration": 15,
    "immediate_display": True,
    "custom_email_responses": True,
    "show_file_name": True,
    "show_file_date": True,
    "show_caption": True,
    "error_email_recipient": "",
    # --- Daily weather card ---
    "weather_time": "08:00",
    "weather_times": [],
    "weather_display_seconds": 60,
    # --- Night light on motion ---
    "night_light_enabled": False,
    "night_light_gpio_pin": 18,
    "night_light_duration": 60,
    "night_light_active_low": False,
    "night_light_only_when_dark": True,
    # --- Special-day automation ---
    "special_days_enabled": False,
    "special_days_file": "special_days.json",
    "special_days_time": "07:00",
    "special_days_display_seconds": 8,
}

# Sensitive keys that may be supplied via environment variables instead of
# living in plaintext in display_config.json. Env wins over the file.
ENV_OVERRIDES = {
    "SELAH_EMAIL_ADDRESS": "email_address",
    "SELAH_EMAIL_PASSWORD": "email_password",
    "SELAH_WEATHER_API_KEY": "weather_api_key",
    "SELAH_WEB_PASSWORD": "web_control_password",
    "SELAH_ERROR_EMAIL": "error_email_recipient",
}


def load_config(path="display_config.json"):
    """Load configuration, layering: defaults < file < secrets.local.json < env.

    Secrets can be kept out of the main (potentially shared/backed-up) config
    by putting them in an untracked ``secrets.local.json`` beside it, or in
    environment variables (see ENV_OVERRIDES). Both are optional, so existing
    setups that keep everything in display_config.json keep working unchanged.
    """
    config = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                user_config = json.load(f)
            config.update(user_config)
        else:
            log_error(f"Config file not found: {path}. Using defaults.")
            save_config(config, path)
    except Exception as e:
        log_error(f"Failed to load config: {e}", critical=True)

    # Overlay untracked local secrets file, if present.
    secrets_path = os.path.join(os.path.dirname(os.path.abspath(path)), "secrets.local.json")
    try:
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                config.update(json.load(f))
    except Exception as e:
        log_error(f"Failed to load secrets.local.json: {e}")

    # Environment variables take final precedence.
    for env_key, cfg_key in ENV_OVERRIDES.items():
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val

    return config


def save_config(config, path="display_config.json"):
    """Save configuration to JSON file.

    Secrets that are being supplied externally (env vars or secrets.local.json)
    are NOT written back to the main config, so editing settings via the F1
    GUI never re-leaks a password into the plaintext file.
    """
    try:
        to_write = dict(config)

        # Drop keys currently provided by environment variables.
        for env_key, cfg_key in ENV_OVERRIDES.items():
            if os.environ.get(env_key):
                to_write.pop(cfg_key, None)

        # Drop keys provided by the local secrets file.
        secrets_path = os.path.join(os.path.dirname(os.path.abspath(path)), "secrets.local.json")
        if os.path.exists(secrets_path):
            try:
                with open(secrets_path, "r") as f:
                    for k in json.load(f).keys():
                        to_write.pop(k, None)
            except Exception:
                pass

        with open(path, "w") as f:
            json.dump(to_write, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save config: {e}", critical=True)
