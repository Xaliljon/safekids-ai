"""Errors of the dataset acquisition platform. All loud, all specific."""

from __future__ import annotations


class AcquisitionError(Exception):
    """Base error for the dataset acquisition platform."""


class ImporterError(AcquisitionError):
    """A raw dataset could not be read in its documented layout."""


class NormalizationError(AcquisitionError):
    """Video normalization failed or produced an unreadable clip."""


class AnnotationFormatError(AcquisitionError):
    """A Guardian video annotation is malformed and was rejected."""


class WorkflowError(AcquisitionError):
    """An illegal review-workflow transition was attempted."""


class DatasetPublishError(AcquisitionError):
    """A gate refused publication (quality, privacy, workflow, version)."""


class DatasetRegistryError(AcquisitionError):
    """A published dataset version is missing, corrupt or tampered."""
