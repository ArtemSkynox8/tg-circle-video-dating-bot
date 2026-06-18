from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import imageio_ffmpeg
import numpy as np
from PIL import Image


FACE_CHECK_SECONDS = (1.0, 2.0)


def has_face_in_first_seconds(video_bytes: bytes, seconds: tuple[float, ...] = FACE_CHECK_SECONDS) -> bool:
    with NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(video_bytes)
        video_path = Path(temp_file.name)

    try:
        return _has_face_like_frame(video_path, seconds)
    finally:
        video_path.unlink(missing_ok=True)


def _has_face_like_frame(video_path: Path, seconds: tuple[float, ...]) -> bool:
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    with TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        for index, second in enumerate(seconds):
            frame_path = temp_dir_path / f"frame_{index}.png"
            if not _extract_frame(ffmpeg_path, video_path, second, frame_path):
                continue
            if _looks_like_visible_person(frame_path):
                return True
    return False


def _looks_like_visible_person(frame_path: Path) -> bool:
    with Image.open(frame_path) as image:
        rgb = np.asarray(image.convert("RGB").resize((160, 160)))

    red = rgb[:, :, 0].astype(np.float32)
    green = rgb[:, :, 1].astype(np.float32)
    blue = rgb[:, :, 2].astype(np.float32)
    brightness = rgb.mean(axis=2)

    brightness_std = float(brightness.std())
    color_std = float(rgb.reshape(-1, 3).std(axis=0).mean())
    edge_score = _edge_score(brightness)
    skin_mask = (
        (red > 55)
        & (green > 35)
        & (blue > 20)
        & (red > green * 0.95)
        & (red > blue * 1.15)
        & ((red - blue) > 12)
        & (brightness > 45)
        & (brightness < 235)
    )
    skin_ratio = float(skin_mask.mean())

    # Closed camera / covered lens frames are usually smooth and nearly one-color.
    if brightness_std < 18 or color_std < 12 or edge_score < 5:
        return False
    return skin_ratio >= 0.03 or (edge_score >= 12 and brightness_std >= 28)


def _edge_score(gray: np.ndarray) -> float:
    horizontal = np.abs(np.diff(gray, axis=1)).mean()
    vertical = np.abs(np.diff(gray, axis=0)).mean()
    return float(horizontal + vertical)


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
