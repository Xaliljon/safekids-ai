"""Domain errors for the Guardian Edge runtime.

Every error carries a human-readable message that is safe to log:
messages must never contain credentials or raw stream URLs
(use ``Camera.redacted_url`` when a URL belongs in a message).
"""


class GuardianEdgeError(Exception):
    """Base class for all Guardian Edge domain errors."""


class CameraError(GuardianEdgeError):
    """Base class for camera-related errors."""


class CameraConfigurationError(CameraError):
    """A camera definition is invalid or conflicts with an existing one."""


class CameraConnectionError(CameraError):
    """A camera stream could not be opened."""


class CameraReadError(CameraError):
    """A connected camera stream stopped delivering frames."""


class DiscoveryError(GuardianEdgeError):
    """Network camera discovery could not be performed."""


class VisionError(GuardianEdgeError):
    """Base class for vision pipeline errors."""


class VisionConfigurationError(VisionError):
    """A vision component or detection value is configured/constructed invalidly."""


class DetectorError(VisionError):
    """A detector failed to produce a result for a frame."""
