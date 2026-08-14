"""Inference profiling: statistics, provenance, and stage accounting.

These tests pin the *methodology*, not the numbers — latency is a property
of the machine, and a test that asserted milliseconds would fail on every
other one. What must hold everywhere: cold start stays separable from
steady state, spread is always reported, and a stage nobody measured never
reports zero.
"""

from __future__ import annotations

import pytest

from guardian_ai.training.profiling import (
    LatencyStats,
    RuntimeConfig,
    StageTimer,
    host_provenance,
)


class TestLatencyStats:
    def test_summarises_a_distribution(self) -> None:
        stats = LatencyStats.of([10.0, 20.0, 30.0, 40.0, 50.0])

        assert stats.mean_ms == pytest.approx(30.0)
        assert stats.p50_ms == pytest.approx(30.0)
        assert stats.min_ms == 10.0
        assert stats.max_ms == 50.0
        assert stats.runs == 5

    def test_is_order_independent(self) -> None:
        forward = LatencyStats.of([1.0, 2.0, 3.0, 4.0])
        shuffled = LatencyStats.of([3.0, 1.0, 4.0, 2.0])
        assert forward.to_dict() == shuffled.to_dict()

    def test_relative_spread_is_how_far_a_sample_can_be_trusted(self) -> None:
        steady = LatencyStats.of([50.0, 50.5, 49.5, 50.0])
        noisy = LatencyStats.of([20.0, 80.0, 35.0, 65.0])

        assert steady.relative_spread < 0.05
        assert noisy.relative_spread > 0.4, (
            "the sprint's own baseline spread ±37%; that has to be visible in the record"
        )

    def test_a_single_sample_has_no_spread_rather_than_crashing(self) -> None:
        stats = LatencyStats.of([42.0])
        assert stats.stdev_ms == 0.0
        assert stats.relative_spread == 0.0

    def test_the_serialised_form_always_carries_spread_and_count(self) -> None:
        # A mean without them is a number nobody can reproduce or dispute.
        payload = LatencyStats.of([1.0, 2.0, 3.0]).to_dict()
        assert {"mean_ms", "p50_ms", "p95_ms", "stdev_ms", "relative_spread", "runs"} <= set(
            payload
        )


class TestRuntimeConfig:
    def test_defaults_match_the_promotion_gate(self) -> None:
        # compare.benchmark_onnx runs the CPU provider with ORT's own
        # defaults; the profiler must start from the same place or its
        # "before" is not the gate's before.
        config = RuntimeConfig()
        assert config.provider == "CPUExecutionProvider"
        assert config.intra_op_threads is None
        assert config.inter_op_threads is None

    def test_label_names_every_dimension_under_test(self) -> None:
        label = RuntimeConfig(intra_op_threads=2, inter_op_threads=1).label
        assert "CPU" in label
        assert "intra=2" in label
        assert "inter=1" in label

    def test_round_trips_to_a_record(self) -> None:
        config = RuntimeConfig(provider="CoreMLExecutionProvider", intra_op_threads=4)
        assert config.to_dict()["provider"] == "CoreMLExecutionProvider"
        assert config.to_dict()["intra_op_threads"] == 4


class TestProvenance:
    def test_records_what_makes_a_latency_number_comparable(self) -> None:
        host = host_provenance()
        for key in ("platform", "machine", "processor", "logical_cpus", "onnxruntime"):
            assert host[key], f"missing provenance: {key}"

    def test_development_measurements_are_labelled_as_such(self) -> None:
        """Sprint 20.2 §11: a Mac number must never be read as an Edge one."""
        host = host_provenance()
        assert host["is_edge_target"] is False
        assert host["measurement_class"] == "development"


class TestStageTimer:
    def test_accumulates_per_stage_across_frames(self) -> None:
        timer = StageTimer()
        for value in (1.0, 3.0):
            timer.record("preprocess", value)
        timer.record("inference", 40.0)

        breakdown = timer.breakdown()
        assert breakdown["preprocess"].mean_ms == pytest.approx(2.0)
        assert breakdown["inference"].runs == 1

    def test_measure_times_the_call_and_returns_its_value(self) -> None:
        timer = StageTimer()
        assert timer.measure("work", lambda: 7) == 7
        assert timer.breakdown()["work"].runs == 1

    def test_a_stage_nobody_measured_is_absent_not_zero(self) -> None:
        # Zero would read as "free", and the point of the breakdown is to
        # stop guessing which stage costs what.
        timer = StageTimer()
        timer.record("inference", 40.0)
        assert "postprocess" not in timer.breakdown()
        assert "postprocess" not in timer.to_dict()["stages"]

    def test_shares_are_relative_to_the_measured_total(self) -> None:
        timer = StageTimer()
        timer.record("preprocess", 25.0)
        timer.record("inference", 75.0)

        payload = timer.to_dict()
        assert payload["total_mean_ms"] == pytest.approx(100.0)
        assert payload["stages"]["inference"]["share_of_total"] == pytest.approx(0.75)

    def test_an_empty_timer_reports_nothing_rather_than_dividing_by_zero(self) -> None:
        assert StageTimer().to_dict() == {"stages": {}, "total_mean_ms": 0.0}
