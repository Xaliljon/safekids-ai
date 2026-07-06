"""Circular buffers: rolling window, non-blocking hot path, eviction."""

from __future__ import annotations

import time
from datetime import timedelta

from camera_fakes import wait_until
from evidence_fixtures import BASE, make_frame

from guardian_edge.infrastructure.evidence.rings import FrameRingBuffer, TrackRingBuffer


def fill(ring: FrameRingBuffer, count: int, camera_id: str = "cam-1") -> None:
    for sequence in range(count):
        ring.on_frame(make_frame(sequence, camera_id=camera_id))


class TestFrameRingBuffer:
    def test_buffers_and_serves_a_time_window(self) -> None:
        ring = FrameRingBuffer(buffer_seconds=30.0, queue_capacity=256)
        ring.start()
        try:
            fill(ring, 20)  # 0.1s apart -> 2s of video
            assert wait_until(lambda: ring.stats()["encoded"] == 20)
            window = ring.snapshot(
                "cam-1", BASE + timedelta(seconds=0.5), BASE + timedelta(seconds=1.5)
            )
            assert [frame.sequence for frame in window] == list(range(5, 16))
            # identity survives buffering (ADR-0007)
            assert window[0].frame_id is not None
            assert window[0].decode().shape == (48, 64, 3)
        finally:
            ring.stop()

    def test_old_frames_are_overwritten(self) -> None:
        ring = FrameRingBuffer(buffer_seconds=1.0, queue_capacity=256)  # keep only ~1s
        ring.start()
        try:
            fill(ring, 50)  # 5s of frames at 0.1s spacing
            assert wait_until(lambda: ring.stats()["encoded"] == 50)
            frames = ring.snapshot("cam-1", BASE, BASE + timedelta(seconds=60))
            assert len(frames) <= 12, "ring must not grow past its window"
            assert frames[-1].sequence == 49, "newest frames are kept"
        finally:
            ring.stop()

    def test_cameras_are_isolated(self) -> None:
        ring = FrameRingBuffer()
        ring.start()
        try:
            ring.on_frame(make_frame(1, camera_id="cam-a"))
            ring.on_frame(make_frame(2, camera_id="cam-b"))
            assert wait_until(lambda: ring.stats()["encoded"] == 2)
            window = ring.snapshot("cam-a", BASE, BASE + timedelta(seconds=60))
            assert [frame.camera_id for frame in window] == ["cam-a"]
        finally:
            ring.stop()

    def test_on_frame_never_blocks_when_encoder_is_down(self) -> None:
        """The hot-path guarantee: encoder stopped, queue full — still fast."""
        ring = FrameRingBuffer()  # never started: nothing drains the queue
        started = time.perf_counter()
        for sequence in range(200):
            ring.on_frame(make_frame(sequence))
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5, f"200 on_frame calls took {elapsed:.3f}s"
        assert ring.stats()["dropped"] > 0, "overflow must drop, not block"

    def test_empty_camera_returns_empty(self) -> None:
        ring = FrameRingBuffer()
        assert ring.snapshot("nope", BASE, BASE + timedelta(seconds=1)) == []


class TestTrackRingBuffer:
    def test_keeps_track_snapshots_by_frame(self) -> None:
        from event_fixtures import make_tracking_result

        from guardian_edge.domain.detection import BoundingBox

        ring = TrackRingBuffer(buffer_seconds=30.0)
        result = make_tracking_result(BoundingBox(x=0.4, y=0.3, width=0.1, height=0.5), step=0)
        ring.on_tracking(result)
        index = ring.by_frame_id(result.camera_id)
        assert result.frame_id in index
        snapshot = index[result.frame_id]
        assert len(snapshot.tracks) == len(result.tracks)
        if snapshot.tracks:
            display_id, confidence, x, y, w, h, state = snapshot.tracks[0]
            assert isinstance(display_id, int)
            assert 0 <= confidence <= 1

    def test_unknown_camera_is_empty(self) -> None:
        ring = TrackRingBuffer()
        assert ring.by_frame_id("nope") == {}


class TestOverlayRenderer:
    def test_overlay_draws_boxes_ids_and_timeline(self) -> None:
        from datetime import timedelta

        import numpy as np

        from guardian_edge.infrastructure.evidence.overlay import render_overlay
        from guardian_edge.infrastructure.evidence.rings import TrackSnapshot

        image = np.zeros((240, 320, 3), dtype=np.uint8)
        snapshot = TrackSnapshot(
            frame_id=make_frame(1).frame_id,
            captured_at=BASE,
            tracks=((7, 0.91, 0.25, 0.25, 0.5, 0.5, "confirmed"),),
        )
        rendered = render_overlay(
            image,
            snapshot,
            captured_at=BASE + timedelta(seconds=10),
            clip_start=BASE,
            clip_end=BASE + timedelta(seconds=30),
            incident_at=BASE + timedelta(seconds=15),
        )
        assert rendered.shape == image.shape
        assert rendered.sum() > 0, "something was drawn"
        assert image.sum() == 0, "the input frame is never mutated"
        # incident marker: red pixels near the middle of the timeline bar
        marker_x = 10 + int((320 - 20) * 0.5)
        marker_region = rendered[240 - 14 : 240 - 4, marker_x - 2 : marker_x + 3]
        assert marker_region[..., 2].max() > 200, "red incident marker present"

    def test_overlay_without_tracks_still_stamps_time_and_timeline(self) -> None:
        from datetime import timedelta

        import numpy as np

        from guardian_edge.infrastructure.evidence.overlay import render_overlay

        image = np.zeros((240, 320, 3), dtype=np.uint8)
        rendered = render_overlay(image, None, BASE, BASE, BASE + timedelta(seconds=30), BASE)
        assert rendered.sum() > 0
