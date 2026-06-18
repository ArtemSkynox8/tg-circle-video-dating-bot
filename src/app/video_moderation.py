from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
import mediapipe as mp


FACE_CHECK_SECONDS = (1.0, 2.0)


def has_face_in_first_seconds(video_bytes: bytes, seconds: tuple[float, ...] = FACE_CHECK_SECONDS) -> bool:
    with NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(video_bytes)
        temp_path = Path(temp_file.name)

    capture: cv2.VideoCapture | None = None
    try:
        capture = cv2.VideoCapture(str(temp_path))
        if not capture.isOpened():
            return False

        with mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5,
        ) as detector:
            for second in seconds:
                capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.process(rgb_frame)
                if result.detections:
                    return True
        return False
    finally:
        if capture is not None:
            capture.release()
        temp_path.unlink(missing_ok=True)
