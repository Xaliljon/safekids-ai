"""WS-Discovery response parsing (pure functions; no network)."""

from guardian_edge.infrastructure.camera.discovery import parse_probe_response

PROBE_MATCH = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope
    xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
    xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:wsdd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
    xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <SOAP-ENV:Body>
    <wsdd:ProbeMatches>
      <wsdd:ProbeMatch>
        <wsa:EndpointReference>
          <wsa:Address>urn:uuid:2419d68a-2dd2-21b2-a205-ec8d59a3f0f2</wsa:Address>
        </wsa:EndpointReference>
        <wsdd:Types>dn:NetworkVideoTransmitter</wsdd:Types>
        <wsdd:Scopes>onvif://www.onvif.org/type/video_encoder
            onvif://www.onvif.org/name/Classroom%201%20Camera
            onvif://www.onvif.org/hardware/DS-2CD2043G2</wsdd:Scopes>
        <wsdd:XAddrs>http://192.168.10.11/onvif/device_service
            http://[fe80::1]/onvif/device_service</wsdd:XAddrs>
      </wsdd:ProbeMatch>
    </wsdd:ProbeMatches>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def test_parses_probe_match() -> None:
    candidate = parse_probe_response(PROBE_MATCH, "192.168.10.11")
    assert candidate is not None
    assert candidate.address == "192.168.10.11"
    assert candidate.endpoint == "http://192.168.10.11/onvif/device_service"
    assert candidate.name == "Classroom 1 Camera"
    assert candidate.hardware == "DS-2CD2043G2"


def test_ignores_malformed_xml() -> None:
    assert parse_probe_response(b"<not-xml", "192.168.10.11") is None


def test_ignores_non_probe_match_envelope() -> None:
    payload = (
        b'<?xml version="1.0"?>'
        b'<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope">'
        b"<e:Body/></e:Envelope>"
    )
    assert parse_probe_response(payload, "192.168.10.11") is None


def test_ignores_probe_match_without_xaddrs() -> None:
    payload = (
        b'<?xml version="1.0"?>'
        b'<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
        b' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
        b"<e:Body><d:ProbeMatches><d:ProbeMatch>"
        b"<d:Scopes>onvif://www.onvif.org/name/NoAddress</d:Scopes>"
        b"</d:ProbeMatch></d:ProbeMatches></e:Body></e:Envelope>"
    )
    assert parse_probe_response(payload, "192.168.10.11") is None


def test_missing_scopes_yield_no_name_or_hardware() -> None:
    payload = (
        b'<?xml version="1.0"?>'
        b'<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
        b' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
        b"<e:Body><d:ProbeMatches><d:ProbeMatch>"
        b"<d:XAddrs>http://192.168.10.20/onvif/device_service</d:XAddrs>"
        b"</d:ProbeMatch></d:ProbeMatches></e:Body></e:Envelope>"
    )
    candidate = parse_probe_response(payload, "192.168.10.20")
    assert candidate is not None
    assert candidate.name is None
    assert candidate.hardware is None
