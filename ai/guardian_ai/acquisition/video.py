"""Deterministic video normalization: every source becomes the same shape.

Whatever a raw dataset ships (AVI, MJPEG, odd fps, portrait phones,
image sequences), the workspace stores exactly one thing:

    H.264 / yuv420p / 640x480 (aspect kept, letterboxed) / 15 fps / mp4,
    metadata stripped, bitexact flags, single encoder thread.

Deterministic outputs: the same input file produces byte-identical
output on every run — so a re-import can be verified by checksum, and
"the video changed" can never hide behind "the encoder felt different".

ffmpeg/ffprobe are system prerequisites (the same binaries the ops
scripts already require); frames are decoded with OpenCV (headless).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.errors import NormalizationError

logger = logging.getLogger(__name__)

TARGET_WIDTH = 640
TARGET_HEIGHT = 480
TARGET_FPS = 15


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float


def probe(path: Path) -> VideoInfo:
    """Read the facts of a video with OpenCV; refuse the unreadable."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise NormalizationError(f"unreadable video: {path}")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or 0.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    if width <= 0 or height <= 0 or frame_count <= 0:
        raise NormalizationError(
            f"empty or broken video: {path} ({width}x{height}, {frame_count} frames)"
        )
    duration = frame_count / fps if fps > 0 else 0.0
    return VideoInfo(width, height, fps, frame_count, duration)


def normalize_video(source: Path, destination: Path) -> VideoInfo:
    """Convert + resize + normalize fps/codec/resolution, deterministically.

    Returns the VideoInfo of the *normalized* clip (annotation frame
    numbers must reference this timeline, never the source's).
    """
    if not source.is_file():
        raise NormalizationError(f"source video missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={TARGET_FPS},format=yuv420p"
    )
    command = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(source),
        "-vf",
        scale,
        "-an",  # audio never enters a Guardian dataset
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-threads",
        "1",  # single thread: deterministic encode order
        "-x264-params",
        "threads=1:sliced-threads=0",
        "-map_metadata",
        "-1",  # strip every source metadata field
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, paths from our own code
            command, capture_output=True, text=True, timeout=600, check=False
        )
    except FileNotFoundError as exc:
        raise NormalizationError(
            "ffmpeg not found — it is a system prerequisite (see QUICK_START.md)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NormalizationError(f"ffmpeg timed out on {source}") from exc
    if result.returncode != 0:
        raise NormalizationError(f"ffmpeg failed on {source}: {result.stderr.strip()[:500]}")
    info = probe(destination)
    if (info.width, info.height) != (TARGET_WIDTH, TARGET_HEIGHT):
        raise NormalizationError(
            f"normalization produced {info.width}x{info.height}, "
            f"expected {TARGET_WIDTH}x{TARGET_HEIGHT}"
        )
    logger.info(
        "normalized %s -> %s (%d frames @ %s fps)",
        source.name,
        destination.name,
        info.frame_count,
        TARGET_FPS,
    )
    return info


def frames_from_images(images: list[Path], destination: Path) -> VideoInfo:
    """Build a normalized clip from an image sequence (UR Fall ships PNGs)."""
    if not images:
        raise NormalizationError("image sequence is empty")
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="guardian-seq-") as staging:
        staging_dir = Path(staging)
        for index, image in enumerate(sorted(images)):
            if not image.is_file():
                raise NormalizationError(f"sequence image missing: {image}")
            shutil.copy2(image, staging_dir / f"{index:06d}{image.suffix.lower()}")
        suffix = sorted(images)[0].suffix.lower()
        pattern = str(staging_dir / f"%06d{suffix}")
        raw = staging_dir / "raw.mp4"
        command = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-framerate",
            str(TARGET_FPS),
            "-i",
            pattern,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            str(raw),
        ]
        result = subprocess.run(  # noqa: S603 - fixed argv
            command, capture_output=True, text=True, timeout=600, check=False
        )
        if result.returncode != 0:
            raise NormalizationError(
                f"ffmpeg failed on image sequence: {result.stderr.strip()[:500]}"
            )
        return normalize_video(raw, destination)


def map_frame(source_frame: int, source_fps: float) -> int:
    """Map a source-timeline frame number onto the normalized timeline."""
    if source_fps <= 0:
        raise NormalizationError(f"cannot map frames at source fps {source_fps}")
    return int(round(source_frame * TARGET_FPS / source_fps))


def ffprobe_json(path: Path) -> dict[str, Any]:
    """ffprobe stream facts (used by quality validation for codec checks)."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(  # noqa: S603 - fixed argv
        command, capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode != 0:
        raise NormalizationError(f"ffprobe failed on {path}: {result.stderr.strip()[:300]}")
    return dict(json.loads(result.stdout))
