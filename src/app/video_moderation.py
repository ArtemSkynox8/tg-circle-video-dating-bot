from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import imageio_ffmpeg


FACE_CHECK_SECONDS = (0.5, 1.0, 2.0)
FACE_CASCADE = None


def has_face_in_first_seconds(video_bytes: bytes, seconds: tuple[float, ...] = FACE_CHECK_SECONDS) -> bool:
    with NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(video_bytes)
        video_path = Path(temp_file.name)

    try:
        return _has_face_on_every_frame(video_path, seconds)
    finally:
        video_path.unlink(missing_ok=True)


def _has_face_on_every_frame(video_path: Path, seconds: tuple[float, ...]) -> bool:
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    with TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        for index, second in enumerate(seconds):
            frame_path = temp_dir_path / f"frame_{index}.png"
            if not _extract_frame(ffmpeg_path, video_path, second, frame_path):
                return False
            if not _frame_has_face(frame_path):
                return False
    return True


def _frame_has_face(frame_path: Path) -> bool:
    import cv2

    global FACE_CASCADE
    if FACE_CASCADE is None:
        FACE_CASCADE = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    frame = cv2.imread(str(frame_path))
    if frame is None:
        return False
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    height, width = gray.shape[:2]
    min_face_size = max(32, min(width, height) // 7)
    faces = FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=5,
        minSize=(min_face_size, min_face_size),
    )
    return len(faces) > 0


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
