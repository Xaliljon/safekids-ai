"""Vision pipeline application layer.

Consumes frames from the camera service via the FrameConsumer contract —
the camera service knows nothing about AI (ADR-0006). Publishes detection
results to consumers; what happens downstream (risk analysis, notification)
is invisible from here.
"""
