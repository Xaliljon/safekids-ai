"""Run a Guardian Box demo for device integration: no cameras required.

Loops the synthetic fall scenario through the full production chain
(detections -> tracking -> events -> risk -> notifications) and exposes
the Device API on the LAN so a phone can pair, receive live incidents,
and confirm/dismiss them. The pairing code is printed at startup.

Usage:
    uv run python -m guardian_edge.tools.device_demo --data-dir /tmp/guardian-demo
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from guardian_edge.api.pairing import PairingManager
from guardian_edge.api.server import DeviceApiServer
from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import FallDetectorConfig, PotentialFallDetector
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.domain.detection import BoundingBox, Detection, ModelDescriptor
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import Track, TrackingResult, TrackState
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel

logger = logging.getLogger("device_demo")

MODEL = ModelDescriptor(name="scripted-scenario", version="1.0.0")
TRACKER = ModelDescriptor(name="bytetrack", version="1.0.0")

STANDING = BoundingBox(x=0.45, y=0.30, width=0.10, height=0.62)
LYING = BoundingBox(x=0.37, y=0.80, width=0.30, height=0.12)


def scenario_boxes() -> list[BoundingBox]:
    def mix(a: BoundingBox, b: BoundingBox, t: float) -> BoundingBox:
        return BoundingBox(
            x=a.x + (b.x - a.x) * t,
            y=a.y + (b.y - a.y) * t,
            width=a.width + (b.width - a.width) * t,
            height=a.height + (b.height - a.height) * t,
        )

    boxes = [STANDING] * 20
    boxes += [mix(STANDING, LYING, (i + 1) / 5) for i in range(5)]
    boxes += [LYING] * 30
    boxes += [mix(LYING, STANDING, (i + 1) / 8) for i in range(8)]
    boxes += [STANDING] * 40  # recovery pause so each loop is a fresh track story
    return boxes


def make_tracking_result(
    box: BoundingBox, sequence: int, track_id: object, captured_at: datetime
) -> TrackingResult:
    frame = Frame(
        camera_id="classroom-1",
        sequence=sequence,
        captured_at=captured_at,
        width=640,
        height=480,
        data=object(),
    )
    detection = Detection(
        detection_id=uuid4(),
        frame_id=frame.frame_id,
        camera_id=frame.camera_id,
        captured_at=captured_at,
        correlation_id=frame.correlation_id,
        label="child",
        confidence=0.93,
        box=box,
    )
    track = Track(
        track_id=track_id,  # type: ignore[arg-type]
        display_id=1,
        camera_id=frame.camera_id,
        state=TrackState.CONFIRMED,
        label="child",
        confidence=0.93,
        box=box,
        last_detection=detection,
        hits=sequence + 1,
        age_frames=sequence + 1,
        frames_since_update=0,
        first_seen_at=captured_at,
        last_seen_at=captured_at,
    )
    return TrackingResult(
        camera_id=frame.camera_id,
        frame_id=frame.frame_id,
        frame_sequence=sequence,
        captured_at=captured_at,
        correlation_id=frame.correlation_id,
        tracks=(track,),
        detection_model=MODEL,
        tracker=TRACKER,
        tracking_ms=0.1,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("demo-data"))
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument("--ws-port", type=int, default=8788)
    parser.add_argument("--interval", type=float, default=0.1, help="frame interval seconds")
    args = parser.parse_args(argv)

    channel = LocalPushChannel(args.data_dir / "outbox")
    notification_engine = NotificationEngine(channel)
    risk_engine = RiskEngine(notification_engine)
    event_engine = EventEngine(
        [PotentialFallDetector(FallDetectorConfig(cooldown_seconds=5.0))], risk_engine
    )
    pairing = PairingManager(args.data_dir)
    server = DeviceApiServer(
        risk_engine=risk_engine,
        push_channel=channel,
        outbox_dir=args.data_dir / "outbox",
        pairing=pairing,
        api_port=args.api_port,
        ws_port=args.ws_port,
    )
    notification_engine.start()
    server.start()
    logger.info("pairing code: %s", pairing.current_code)
    logger.info("scenario loop: a child falls roughly every %.0f seconds", 103 * args.interval)

    boxes = scenario_boxes()
    sequence = 0
    try:
        while True:
            track_id = uuid4()  # a fresh track per loop -> a fresh incident story
            for box in boxes:
                event_engine(
                    make_tracking_result(box, sequence, track_id, datetime.now(tz=timezone.utc))
                )
                sequence += 1
                time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.stop()
        notification_engine.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
