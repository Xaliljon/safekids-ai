"""Device pairing: how a phone becomes trusted (ADR-0015).

The box displays a short-lived pairing code (today: logs it; the physical
device will show it on its status display). A phone submits the code once
and receives a long-lived random token; the code is consumed and a new one
is generated. No accounts, no cloud login — trust is local, explicit, and
per-device (docs/03: never trust the network, never trust external
devices; trust is granted by a human who can read the box's display).

Trusted devices persist across restarts in a state file inside the box's
data directory.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRUST_FILE_NAME = "trusted_devices.json"
_CODE_DIGITS = 6
_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class TrustedDevice:
    token: str
    device_name: str
    paired_at: str


class PairingManager:
    """Issues pairing codes and verifies device tokens."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._lock = threading.Lock()
        self._devices: dict[str, TrustedDevice] = {}
        self._code = self._new_code()
        self._load()
        logger.warning("device pairing code: %s", self._code)  # future: box display

    @property
    def current_code(self) -> str:
        with self._lock:
            return self._code

    def pair(self, code: str, device_name: str) -> str | None:
        """Exchange a valid pairing code for a device token; None if invalid.

        Codes are single-use: success consumes the code and mints a new one.
        """
        clean_name = device_name.strip() or "unnamed-device"
        with self._lock:
            if not secrets.compare_digest(code.strip(), self._code):
                logger.warning("pairing attempt with wrong code from '%s'", clean_name)
                return None
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            self._devices[token] = TrustedDevice(
                token=token,
                device_name=clean_name,
                paired_at=datetime.now(tz=timezone.utc).isoformat(),
            )
            self._code = self._new_code()
            self._save_locked()
        logger.warning("device '%s' paired; new pairing code: %s", clean_name, self._code)
        return token

    def device_for(self, token: str) -> TrustedDevice | None:
        with self._lock:
            return self._devices.get(token)

    def is_trusted(self, token: str) -> bool:
        return self.device_for(token) is not None

    # ------------------------------------------------------------ internals

    def _new_code(self) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(_CODE_DIGITS))

    def _load(self) -> None:
        path = self._data_dir / TRUST_FILE_NAME
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self._devices = {
                    entry["token"]: TrustedDevice(
                        token=str(entry["token"]),
                        device_name=str(entry["device_name"]),
                        paired_at=str(entry["paired_at"]),
                    )
                    for entry in raw
                }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            logger.exception("trusted-devices state unreadable; starting with no devices")

    def _save_locked(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / TRUST_FILE_NAME
        temporary = path.with_name(TRUST_FILE_NAME + ".tmp")
        temporary.write_text(
            json.dumps(
                [
                    {
                        "token": device.token,
                        "device_name": device.device_name,
                        "paired_at": device.paired_at,
                    }
                    for device in self._devices.values()
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
