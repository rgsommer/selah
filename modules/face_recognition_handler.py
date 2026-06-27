"""Facial recognition prioritization - boost photos containing specific faces."""

import os
from modules.logger import log_error

try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False

_known_encodings = {}
_encoding_cache = {}  # filepath -> list of face encodings (the expensive part)


def prioritize_images(file_list, config):
    """Reorder file_list so images with recognized faces appear more frequently.

    If face_recognition is not installed, returns the list unchanged.
    Priority faces (e.g., birthday child) are boosted to appear 3x more often.
    """
    if not HAS_FACE_RECOGNITION:
        return file_list
    if not file_list:
        return file_list

    try:
        # Load known faces if configured
        known_faces_dir = config.get("known_faces_dir", "known_faces")
        _load_known_faces(known_faces_dir)

        priority_person = config.get("priority_person", None)
        image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

        scored = []
        for filepath in file_list:
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in image_extensions:
                scored.append((filepath, 1))  # Videos get neutral score
                continue

            score = _score_image(filepath, priority_person)
            scored.append((filepath, score))

        # Sort by score descending, then interleave high-priority images
        scored.sort(key=lambda x: x[1], reverse=True)

        # Build final list: high-score images appear multiple times
        result = []
        normal = []
        boosted = []
        for filepath, score in scored:
            normal.append(filepath)
            if score >= 3:
                boosted.append(filepath)
                boosted.append(filepath)  # Extra copies for more frequent display

        # Interleave boosted images into the normal list
        if boosted:
            interval = max(1, len(normal) // len(boosted))
            idx = 0
            for i, filepath in enumerate(normal):
                result.append(filepath)
                if idx < len(boosted) and (i + 1) % interval == 0:
                    result.append(boosted[idx])
                    idx += 1
        else:
            result = normal

        return result

    except Exception as e:
        log_error(f"Face recognition prioritization failed: {e}")
        return file_list


def _load_known_faces(known_faces_dir):
    """Load known face encodings from a directory of labeled images."""
    global _known_encodings
    if _known_encodings:
        return  # Already loaded

    if not os.path.isdir(known_faces_dir):
        return

    try:
        for filename in os.listdir(known_faces_dir):
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            name = os.path.splitext(filename)[0].lower()
            filepath = os.path.join(known_faces_dir, filename)
            image = face_recognition.load_image_file(filepath)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                _known_encodings[name] = encodings[0]
    except Exception as e:
        log_error(f"Failed to load known faces: {e}")


def _get_encodings(filepath):
    """Return cached face encodings for an image (detect once, reuse forever).

    Detection (face_locations + face_encodings) is the expensive step, so we
    cache it per file. The priority match is computed cheaply from these, which
    means changing priority_person (e.g. a new birthday) costs nothing to
    re-evaluate — no re-detection.
    """
    global _encoding_cache
    if filepath in _encoding_cache:
        return _encoding_cache[filepath]
    try:
        image = face_recognition.load_image_file(filepath)
        locations = face_recognition.face_locations(image, model="hog")
        encodings = face_recognition.face_encodings(image, locations) if locations else []
        _encoding_cache[filepath] = encodings
        return encodings
    except Exception:
        _encoding_cache[filepath] = []
        return []


def _score_image(filepath, priority_person=None):
    """Score an image by face content. Higher = more priority."""
    encodings = _get_encodings(filepath)
    if not encodings:
        return 0

    score = len(encodings)  # more faces = slightly higher base score

    if priority_person and _known_encodings:
        target = _known_encodings.get(priority_person.lower())
        if target is not None:
            for encoding in encodings:
                if face_recognition.compare_faces([target], encoding, tolerance=0.6)[0]:
                    score += 5  # big boost for the priority person
                    break

    return score
