"""Detector-specific training code, isolated by vendor/architecture.

Guardian AI does not own detector implementations (architecture/
detector-integration.md) — this package exists so that fact is true by
construction: every subpackage here wraps one external, unmodified
detector library behind the ``DetectorFamily`` port. Nothing outside
these subpackages may import a detector's own types.
"""
