"""Inference runtime application layer.

Model-agnostic: loads, validates, warms up, and measures models behind the
InferenceEngine port without knowing what any model does. Vision detectors
(and later audio) compose engines from here; the runtime itself never
interprets tensors (ADR-0008).
"""
