"""ONVIF WS-Discovery: find camera candidates on the local network.

Implements the CameraDiscovery port with a raw WS-Discovery multicast probe
(no ONVIF client dependency). Responses are untrusted network input and are
parsed with defusedxml.

Discovery is assistive only: candidates are shown to an operator, who must
explicitly register a camera with its RTSP URL. The runtime never auto-trusts
devices found on the network (docs/03, security by default).
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
from urllib.parse import unquote

from defusedxml import ElementTree

from guardian_edge.domain.discovery import DiscoveredCamera
from guardian_edge.domain.errors import DiscoveryError

logger = logging.getLogger(__name__)

MULTICAST_GROUP = "239.255.255.250"
MULTICAST_PORT = 3702
DEFAULT_PROBE_TIMEOUT_SECONDS = 3.0
_BUFFER_SIZE = 65_535

_NAMESPACES = {
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
}
_SCOPE_NAME_PREFIX = "onvif://www.onvif.org/name/"
_SCOPE_HARDWARE_PREFIX = "onvif://www.onvif.org/hardware/"

_PROBE_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
    ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header>"
    "<w:MessageID>uuid:{message_id}</w:MessageID>"
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">'
    "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
    "</e:Header>"
    "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
    "</e:Envelope>"
)


def parse_probe_response(payload: bytes, sender_address: str) -> DiscoveredCamera | None:
    """Parse one WS-Discovery reply; None if it is not a usable ProbeMatch."""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        logger.debug("discovery: ignoring malformed reply from %s", sender_address)
        return None
    match = root.find(".//d:ProbeMatch", _NAMESPACES)
    if match is None:
        return None
    xaddrs_element = match.find("d:XAddrs", _NAMESPACES)
    xaddrs = (xaddrs_element.text or "").split() if xaddrs_element is not None else []
    if not xaddrs:
        return None
    scopes_element = match.find("d:Scopes", _NAMESPACES)
    name, hardware = _parse_scopes(scopes_element.text or "" if scopes_element is not None else "")
    return DiscoveredCamera(
        address=sender_address,
        endpoint=xaddrs[0],
        name=name,
        hardware=hardware,
    )


def _parse_scopes(scopes: str) -> tuple[str | None, str | None]:
    name: str | None = None
    hardware: str | None = None
    for scope in scopes.split():
        if scope.startswith(_SCOPE_NAME_PREFIX):
            name = unquote(scope.removeprefix(_SCOPE_NAME_PREFIX))
        elif scope.startswith(_SCOPE_HARDWARE_PREFIX):
            hardware = unquote(scope.removeprefix(_SCOPE_HARDWARE_PREFIX))
    return name, hardware


class OnvifWsDiscovery:
    """CameraDiscovery implementation using a WS-Discovery multicast probe."""

    def discover(
        self, timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS
    ) -> list[DiscoveredCamera]:
        """Probe the local network and collect replies until the timeout.

        Returns candidates deduplicated by endpoint. Raises DiscoveryError
        when the probe itself cannot be sent (e.g. no network).
        """
        probe = _PROBE_TEMPLATE.format(message_id=uuid.uuid4()).encode("utf-8")
        found: dict[str, DiscoveredCamera] = {}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
                sock.sendto(probe, (MULTICAST_GROUP, MULTICAST_PORT))
                deadline = time.monotonic() + timeout_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    try:
                        payload, (sender, _port) = sock.recvfrom(_BUFFER_SIZE)
                    except TimeoutError:
                        break
                    candidate = parse_probe_response(payload, sender)
                    if candidate is not None:
                        found[candidate.endpoint] = candidate
        except OSError as exc:
            raise DiscoveryError(f"WS-Discovery probe failed: {exc}") from exc
        logger.info("discovery: found %d camera candidate(s)", len(found))
        return list(found.values())
