"""Camera-based motion detection with optional night light and recording."""

import time
import os
import datetime
from modules.logger import log_error
from modules.time_manager import is_display_off

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

# RPi.GPIO is only present on a Raspberry Pi; everything degrades to a no-op
# (with a single log line) on a dev laptop so motion detection still works.
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except Exception:
    GPIO = None
    HAS_GPIO = False

_camera = None
_previous_frame = None
_last_motion_time = 0
_recording = False
_video_writer = None

# Night-light state
_gpio_ready = False
_light_on = False
_light_off_at = 0
_gpio_warned = False
_LAST_CONFIG = {}  # remembered so the no-arg cleanup() can drive the pin


def detect_motion(config, screens=None):
    """Check camera for motion. Returns True if motion detected.

    Uses OpenCV background subtraction to detect significant frame changes.
    Optionally triggers night light or video recording.
    """
    global _camera, _previous_frame, _last_motion_time, _recording, _video_writer

    # Always service the night light, even on frames with no motion, so it
    # switches off again after its timeout.
    _service_night_light(config)

    if not config.get("motion_detection_enabled", False):
        return False

    if not HAS_OPENCV:
        log_error("OpenCV not available for motion detection")
        return False

    try:
        # Initialize camera if needed
        if _camera is None:
            _camera = cv2.VideoCapture(0)
            if not _camera.isOpened():
                # Try Pi camera
                _camera = cv2.VideoCapture(-1)
            if not _camera.isOpened():
                log_error("No camera available for motion detection")
                return False
            # Lower resolution for faster processing
            _camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            _camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        ret, frame = _camera.read()
        if not ret or frame is None:
            return False

        # Convert to grayscale and blur
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if _previous_frame is None:
            _previous_frame = gray
            return False

        # Compute absolute difference
        frame_delta = cv2.absdiff(_previous_frame, gray)
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        # Find contours (motion regions)
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion_detected = False
        min_area = config.get("motion_min_area", 500)

        for contour in contours:
            if cv2.contourArea(contour) >= min_area:
                motion_detected = True
                break

        _previous_frame = gray

        if motion_detected:
            _last_motion_time = time.time()

            # Optional: trigger the night light
            if config.get("night_light_enabled", False):
                _trigger_night_light(config)

            # Optional: start recording
            if config.get("motion_recording_enabled", False) and not _recording:
                _start_recording(frame, config)
            return True
        else:
            # Stop recording after motion ends
            if _recording and time.time() - _last_motion_time > 10:
                _stop_recording()
            return False

    except Exception as e:
        log_error(f"Motion detection error: {e}")
        return False


def _start_recording(frame, config):
    """Start recording video when motion is detected."""
    global _recording, _video_writer
    try:
        recordings_dir = config.get("recordings_dir", "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(recordings_dir, f"motion_{timestamp}.avi")

        h, w = frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        _video_writer = cv2.VideoWriter(filepath, fourcc, 10, (w, h))
        _recording = True
    except Exception as e:
        log_error(f"Failed to start motion recording: {e}")


def _stop_recording():
    """Stop video recording."""
    global _recording, _video_writer
    try:
        if _video_writer:
            _video_writer.release()
        _recording = False
        _video_writer = None
    except Exception as e:
        log_error(f"Failed to stop recording: {e}")


def _ensure_gpio(config):
    """Lazily configure the night-light GPIO pin. Returns True if usable."""
    global _gpio_ready, _gpio_warned
    if _gpio_ready:
        return True
    if not HAS_GPIO:
        if not _gpio_warned:
            log_error("RPi.GPIO not available — night light disabled (running off-Pi?)")
            _gpio_warned = True
        return False
    try:
        pin = int(config.get("night_light_gpio_pin", 18))
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT)
        # Start in the OFF state (respecting active-low relay boards).
        GPIO.output(pin, _light_level(config, on=False))
        _gpio_ready = True
        return True
    except Exception as e:
        log_error(f"Night-light GPIO setup failed: {e}")
        _gpio_warned = True
        return False


def _light_level(config, on):
    """Map logical on/off to the GPIO level, honoring active-low wiring."""
    active_low = config.get("night_light_active_low", False)
    if active_low:
        return GPIO.LOW if on else GPIO.HIGH
    return GPIO.HIGH if on else GPIO.LOW


def _trigger_night_light(config):
    """Turn the night light on (or extend its on-time) when motion fires."""
    global _light_on, _light_off_at

    # Only light up in the dark if requested (default: yes — a night light by
    # day is pointless and wastes the bulb).
    if config.get("night_light_only_when_dark", True):
        if not is_display_off(datetime.datetime.now().time(), config):
            return

    if not _ensure_gpio(config):
        return

    try:
        pin = int(config.get("night_light_gpio_pin", 18))
        if not _light_on:
            GPIO.output(pin, _light_level(config, on=True))
            _light_on = True
            print("[Selah] Night light ON (motion)")
        # Extend the timeout on every fresh motion event.
        _light_off_at = time.time() + config.get("night_light_duration", 60)
    except Exception as e:
        log_error(f"Night-light trigger failed: {e}")


def _service_night_light(config):
    """Switch the night light off once its timeout elapses."""
    global _light_on, _light_off_at, _LAST_CONFIG
    _LAST_CONFIG = config
    if not _light_on or not _gpio_ready:
        return
    if time.time() < _light_off_at:
        return
    try:
        pin = int(config.get("night_light_gpio_pin", 18))
        GPIO.output(pin, _light_level(config, on=False))
        print("[Selah] Night light OFF (timeout)")
    except Exception as e:
        log_error(f"Night-light off failed: {e}")
    finally:
        _light_on = False


def cleanup():
    """Release camera and GPIO resources."""
    global _camera, _gpio_ready, _light_on
    if _camera:
        _camera.release()
        _camera = None
    _stop_recording()
    # Leave the night light off and release the pin.
    if _gpio_ready and HAS_GPIO:
        try:
            pin = int(_LAST_CONFIG.get("night_light_gpio_pin", 18))
            GPIO.output(pin, _light_level(_LAST_CONFIG, on=False))
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
    _gpio_ready = False
    _light_on = False
