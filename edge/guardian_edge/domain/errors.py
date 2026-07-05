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


class RiskError(GuardianEdgeError):
    """Base class for risk engine errors."""


class UnknownIncidentError(RiskError):
    """A referenced incident is not open in this engine."""


class InferenceError(GuardianEdgeError):
    """Base class for inference runtime errors."""


class ModelValidationError(InferenceError):
    """A model manifest or tensor specification is invalid."""


class ModelLoadError(InferenceError):
    """A model artifact could not be loaded or disagrees with its manifest."""


class ModelRegistryError(InferenceError):
    """A model could not be found or verified in the registry."""


class TensorValidationError(InferenceError):
    """An input tensor disagrees with the model's declared contract."""


class ModelInstallError(InferenceError):
    """A model bundle could not be installed into the zoo."""


class ModelLicenseError(InferenceError):
    """A model's license is missing or not allowed on this device."""


class ModelCompatibilityError(InferenceError):
    """A model requires a runtime this device does not provide."""
