"""EngineDetector: stage composition, thresholds, and config."""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from camera_fakes import make_frame

from guardian_edge.application.inference.metrics import EngineMetrics, EngineMetricsRecorder
from guardian_edge.application.vision.detector import DetectorConfig, EngineDetector
from guardian_edge.application.vision.ports import PreprocessedFrame, RawDetection
from guardian_edge.domain.detection import BoundingBox, ModelDescriptor
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.model import ModelManifest, TensorSpec

MANIFEST = ModelManifest(
    model=ModelDescriptor(name="any-model", version="1.0.0"),
    task="object-detection",
    file_name="model.onnx",
    inputs=(TensorSpec(name="image", dtype="float32", shape=(1, 3, None, None)),),
    outputs=(TensorSpec(name="detections", dtype="float32", shape=(1, 10, 6)),),
    metadata={"labels": ["person", "child"], "confidence_threshold": 0.6},
)


def raw(confidence: float, x: float = 0.1, label_index: int = 0) -> RawDetection:
    return RawDetection(
        label_index=label_index,
        confidence=confidence,
        box=BoundingBox(x=x, y=0.1, width=0.2, height=0.2),
    )


class FakeEngine:
    manifest = MANIFEST

    def __init__(self) -> None:
        self.received_inputs: list[Mapping[str, Any]] = []
        self.closed = False

    def infer(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        self.received_inputs.append(inputs)
        return {"detections": "raw-output"}

    def warmup(
        self, iterations: int = 2, shapes: Mapping[str, tuple[int, ...]] | None = None
    ) -> None:
        pass

    def metrics(self) -> EngineMetrics:
        return EngineMetricsRecorder().snapshot()

    def close(self) -> None:
        self.closed = True


class FakePreprocessor:
    def preprocess(self, frame: Frame) -> PreprocessedFrame:
        return PreprocessedFrame(inputs={"image": f"tensor-{frame.sequence}"}, meta="meta-token")


class FakeDecoder:
    def __init__(self, candidates: Sequence[RawDetection]) -> None:
        self._candidates = list(candidates)
        self.received: list[tuple[Mapping[str, Any], Any]] = []

    def decode(self, outputs: Mapping[str, Any], meta: Any) -> list[RawDetection]:
        self.received.append((outputs, meta))
        return self._candidates


def make_detector(
    candidates: Sequence[RawDetection],
    config: DetectorConfig | None = None,
) -> tuple[EngineDetector, FakeEngine, FakeDecoder]:
    engine = FakeEngine()
    decoder = FakeDecoder(candidates)
    detector = EngineDetector(
        engine=engine,
        preprocessor=FakePreprocessor(),
        decoder=decoder,
        config=config or DetectorConfig(labels=("person", "child"), confidence_threshold=0.5),
    )
    return detector, engine, decoder


def test_stages_compose_and_meta_flows_from_pre_to_post() -> None:
    detector, engine, decoder = make_detector([raw(0.9)])
    result = detector.detect(make_frame("cam-1", 5))
    assert engine.received_inputs == [{"image": "tensor-5"}]
    assert decoder.received == [({"detections": "raw-output"}, "meta-token")]
    assert result.detections[0].label == "person"
    assert result.inference_ms >= 0.0
    assert result.model == MANIFEST.model


def test_confidence_filter_drops_weak_candidates_before_nms() -> None:
    detector, _, _ = make_detector([raw(0.9, x=0.1), raw(0.49, x=0.6)])
    result = detector.detect(make_frame("cam-1", 1))
    assert [d.confidence for d in result.detections] == [0.9]


def test_nms_suppresses_overlapping_duplicates() -> None:
    detector, _, _ = make_detector([raw(0.9, x=0.10), raw(0.7, x=0.11)])
    result = detector.detect(make_frame("cam-1", 1))
    assert len(result.detections) == 1
    assert result.detections[0].confidence == 0.9


def test_max_detections_caps_by_confidence() -> None:
    candidates = [raw(0.6, x=0.0), raw(0.9, x=0.3), raw(0.7, x=0.6)]
    config = DetectorConfig(labels=("person",), confidence_threshold=0.5, max_detections=2)
    detector, _, _ = make_detector(candidates, config)
    result = detector.detect(make_frame("cam-1", 1))
    assert [d.confidence for d in result.detections] == [0.9, 0.7]


def test_descriptor_comes_from_the_engine_manifest() -> None:
    detector, _, _ = make_detector([])
    assert detector.descriptor == MANIFEST.model


def test_close_releases_the_engine() -> None:
    detector, engine, _ = make_detector([])
    detector.close()
    assert engine.closed


class TestDetectorConfig:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"labels": ()},
            {"labels": (" ",)},
            {"labels": ("person",), "confidence_threshold": 1.5},
            {"labels": ("person",), "nms_iou_threshold": 0.0},
            {"labels": ("person",), "max_detections": 0},
        ],
    )
    def test_rejects_invalid_values(self, kwargs: dict[str, Any]) -> None:
        with pytest.raises(VisionConfigurationError):
            DetectorConfig(**kwargs)

    def test_from_manifest_reads_labels_and_thresholds(self) -> None:
        config = DetectorConfig.from_manifest(MANIFEST)
        assert config.labels == ("person", "child")
        assert config.confidence_threshold == 0.6
        assert config.nms_iou_threshold == 0.45  # default, not in metadata

    def test_from_manifest_overrides_win(self) -> None:
        config = DetectorConfig.from_manifest(MANIFEST, confidence_threshold=0.9)
        assert config.confidence_threshold == 0.9

    def test_from_manifest_requires_labels(self) -> None:
        manifest_without_labels = ModelManifest(
            model=MANIFEST.model,
            task=MANIFEST.task,
            file_name=MANIFEST.file_name,
            inputs=MANIFEST.inputs,
            outputs=MANIFEST.outputs,
        )
        with pytest.raises(VisionConfigurationError, match="labels"):
            DetectorConfig.from_manifest(manifest_without_labels)
