"""Camera discovery results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveredCamera:
    """A camera candidate found on the local network.

    Candidates are suggestions for the operator only. Discovery never
    registers a camera by itself: an operator must review each candidate and
    explicitly configure its RTSP URL and credentials (never trust external
    devices — docs/03, security by default; human in control — docs/04).
    """

    address: str
    """IP address the probe response came from."""

    endpoint: str
    """ONVIF device service endpoint (first XAddr)."""

    name: str | None = None
    """Device name advertised in ONVIF scopes, if any."""

    hardware: str | None = None
    """Hardware model advertised in ONVIF scopes, if any."""
