from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory


FACE_CHECK_SECONDS = (1.0, 2.0)


def has_face_in_first_seconds(video_bytes: bytes, seconds: tuple[float, ...] = FACE_CHECK_SECONDS) -> bool:
    with NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(video_bytes)
        video_path = Path(temp_file.name)

    try:
        return _has_face(video_path, seconds)
    finally:
        video_path.unlink(missing_ok=True)


def _has_face(video_path: Path, seconds: tuple[float, ...]) -> bool:
    import imageio_ffmpeg
    import mediapipe as mp
    import numpy as np
    from PIL import Image

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    with TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        with mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5,
        ) as detector:
            for index, second in enumerate(seconds):
                frame_path = temp_dir_path / f"frame_{index}.png"
                if not _extract_frame(ffmpeg_path, video_path, second, frame_path):
                    continue
                with Image.open(frame_path) as image:
                    rgb_frame = np.asarray(image.convert("RGB"))
                result = detector.process(rgb_frame)
                if result.detections:
                    return True
    return False


def _extract_frame(ffmpeg_path: str, video_path: Path, second: float, frame_path: Path) -> bool:
    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        f"{second:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-f",
        "image2",
        str(frame_path),
    ]
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return frame_path.exists() and frame_path.stat().st_size > 0
