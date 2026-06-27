"""Display on/off scheduling based on configured times."""

import os
import time
import datetime
from modules.logger import log_error


def apply_timezone(config):
    """Apply the configured timezone process-wide so all local times use it.

    Setting TZ + time.tzset() makes datetime.now()/localtime honor the zone
    (e.g. "America/Toronto" = Eastern with automatic DST) without needing root
    to change the system clock. Call once at startup.
    """
    tz = config.get("timezone", "")
    if not tz:
        return
    try:
        os.environ["TZ"] = tz
        time.tzset()
        print(f"[Selah] Timezone set to {tz} (current local time {datetime.datetime.now():%Y-%m-%d %H:%M})")
    except Exception as e:
        log_error(f"Failed to apply timezone '{tz}': {e}")


def is_display_off(current_time, config):
    """Check if the display should be off based on on_time and off_time.

    Args:
        current_time: datetime.time object
        config: dict with 'on_time' and 'off_time' as "HH:MM" strings

    Returns:
        True if display should be off (night mode), False if it should be on.
    """
    try:
        on_str = config.get("on_time", "06:00")
        off_str = config.get("off_time", "22:00")

        on_time = datetime.datetime.strptime(on_str, "%H:%M").time()
        off_time = datetime.datetime.strptime(off_str, "%H:%M").time()

        if on_time < off_time:
            # Normal case: on at 06:00, off at 22:00
            # Display is OFF if current_time < on_time or current_time >= off_time
            return current_time < on_time or current_time >= off_time
        else:
            # Overnight case: on at 22:00, off at 06:00
            # Display is OFF if current_time >= off_time and current_time < on_time
            return off_time <= current_time < on_time

    except Exception as e:
        log_error(f"Time manager error: {e}")
        return False  # Default to display on
