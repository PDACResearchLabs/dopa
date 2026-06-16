"""Webcam capture — grabs a single frame, returns JPEG bytes."""

import io
import logging
import cv2
import numpy as np
from .config import Config

logger = logging.getLogger(__name__)


class CameraError(Exception):
    """Webcam not available, permission denied, or capture failed."""


def capture_frame(config: Config) -> bytes | None:
    """Capture a single frame from the webcam. Returns JPEG bytes or None if unavailable."""
    cap = cv2.VideoCapture(config.camera_index)
    if not cap.isOpened():
        cap.release()
        raise CameraError(
            f"Camera index {config.camera_index} not available. "
            "Check permissions (System Settings > Privacy > Camera) "
            "or try a different camera_index."
        )

    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            raise CameraError("Camera opened but frame capture failed.")

        # Resize if too large
        h, w = frame.shape[:2]
        max_dim = config.max_image_dimension
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Encode as JPEG
        success, jpg = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality]
        )
        if not success:
            raise CameraError("JPEG encoding failed.")

        return jpg.tobytes()

    finally:
        cap.release()


def extract_local_features(frame_bytes: bytes) -> dict:
    """
    Fast local feature extraction without calling an LLM.
    Face detection, motion candidates, basic image stats.
    Used on every frame (deep analysis runs less frequently).
    """
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)

    features: dict = {}

    # Face detection via Haar cascade
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    features["face_count"] = len(faces.tolist()) if len(faces) else 0

    if len(faces) == 1:
        x, y, w, h = faces[0]
        features["face_bbox"] = (int(x), int(y), int(w), int(h))
        face_roi = img[y : y + h, x : x + w]

        # Brightness of face region
        features["face_brightness"] = float(np.mean(face_roi))

        # Face size relative to frame — proxy for distance from screen
        features["face_ratio"] = round((w * h) / (img.shape[0] * img.shape[1]), 4)

    elif len(faces) == 0:
        features["presence"] = "absent"
    elif len(faces) > 1:
        features["face_count_note"] = f"multiple_faces_{len(faces)}"

    # Frame-level stats
    features["frame_mean_brightness"] = round(float(np.mean(img)), 1)
    features["frame_std_brightness"] = round(float(np.std(img)), 1)

    return features
