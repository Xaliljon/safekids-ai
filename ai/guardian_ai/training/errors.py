"""Training platform errors — every failure names its cause."""

from __future__ import annotations


class TrainingError(Exception):
    """Base for everything the training platform raises."""


class TrainingConfigurationError(TrainingError):
    """The training config is invalid or references the unavailable."""


class ExperimentError(TrainingError):
    """Experiment tracking failed (missing run, corrupt record, ...)."""


class ExportRejectedError(TrainingError):
    """The exported model failed validation — it must not ship."""


class CompatibilityError(TrainingError):
    """The artifact violates the Guardian Edge contract."""


class PromotionError(TrainingError):
    """Promotion refused (no approval, failed gates, zoo conflict)."""
