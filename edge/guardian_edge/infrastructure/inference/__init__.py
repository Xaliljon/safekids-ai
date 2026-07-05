"""Inference runtime infrastructure: model backends and the model registry.

ONNX Runtime is the canonical, portable backend (ADR-0001 §7); a TensorRT
engine joins on Jetson behind the same InferenceEngine port. Task-level
detectors live in ``infrastructure/vision`` and compose engines from here.
"""
