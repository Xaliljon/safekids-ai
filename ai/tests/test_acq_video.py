"""Video normalization: one shape for every source, byte-deterministic."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from acquisition_fixtures import write_video

from guardian_ai.acquisition.errors import NormalizationError
from guardian_ai.acquisition.video import (
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    ffprobe_json,
    frames_from_images,
    map_frame,
    normalize_video,
    probe,
)


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_video(
        tmp_path_factory.mktemp("src") / "odd.mp4",
        frames=40,
        size=(322, 198),
        fps=27.0,
        seed=9,
    )


def test_probe_reads_the_facts(source: Path) -> None:
    info = probe(source)
    assert (info.width, info.height) == (322, 198)
    assert info.frame_count == 40
    assert info.fps == pytest.approx(27.0, abs=0.5)


def test_probe_refuses_missing_and_garbage(tmp_path: Path) -> None:
    with pytest.raises(NormalizationError, match="unreadable"):
        probe(tmp_path / "absent.mp4")
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video at all")
    with pytest.raises(NormalizationError):
        probe(garbage)


def test_normalize_converts_resolution_fps_codec(source: Path, tmp_path: Path) -> None:
    destination = tmp_path / "normalized.mp4"
    info = normalize_video(source, destination)
    assert (info.width, info.height) == (TARGET_WIDTH, TARGET_HEIGHT)
    assert info.fps == pytest.approx(TARGET_FPS, abs=0.1)
    stream = ffprobe_json(destination)["streams"][0]
    assert stream["codec_name"] == "h264"


def test_normalization_is_deterministic(source: Path, tmp_path: Path) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    normalize_video(source, first)
    normalize_video(source, second)
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )


def test_normalize_refuses_missing_source(tmp_path: Path) -> None:
    with pytest.raises(NormalizationError, match="missing"):
        normalize_video(tmp_path / "absent.avi", tmp_path / "out.mp4")


def test_image_sequence_becomes_a_clip(tmp_path: Path) -> None:
    import cv2
    import numpy as np

    images = []
    for index in range(12):
        frame = np.full((120, 160, 3), 90, dtype=np.uint8)
        cv2.rectangle(frame, (10 + index * 5, 30), (40 + index * 5, 90), (0, 0, 255), -1)
        path = tmp_path / f"img-{index:03d}.png"
        cv2.imwrite(str(path), frame)
        images.append(path)
    info = frames_from_images(images, tmp_path / "seq.mp4")
    assert (info.width, info.height) == (TARGET_WIDTH, TARGET_HEIGHT)
    assert info.frame_count == 12


def test_image_sequence_refuses_empty_and_missing(tmp_path: Path) -> None:
    with pytest.raises(NormalizationError, match="empty"):
        frames_from_images([], tmp_path / "out.mp4")
    with pytest.raises(NormalizationError, match="missing"):
        frames_from_images([tmp_path / "nope.png"], tmp_path / "out.mp4")


def test_map_frame_source_to_normalized_timeline() -> None:
    assert map_frame(30, source_fps=30.0) == 15  # 1s at 30fps -> 1s at 15fps
    assert map_frame(0, source_fps=25.0) == 0
    with pytest.raises(NormalizationError, match="fps"):
        map_frame(10, source_fps=0.0)
