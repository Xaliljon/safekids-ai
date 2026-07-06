"""Evidence-at-rest encryption: AES-256-GCM, key stored away from clips.

No plaintext clip ever touches the disk (ADR-0017): media bytes are
encrypted in memory and written in one step; serving decrypts to memory
only. GCM gives integrity too — a tampered file fails loudly instead of
playing corrupted evidence.

The key lives under ``data/keys`` (mode 0600), the evidence under
``evidence/`` — separate directories, so a copied evidence folder is
useless without the box. Whole-disk encryption of the key itself is the
device-provisioning layer's job (hardware/firmware roadmap).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from guardian_edge.domain.errors import GuardianEdgeError

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12
_MAGIC = b"GEV1"  # guardian evidence v1 — refuse to decrypt foreign blobs


class EvidenceCryptoError(GuardianEdgeError):
    """Encryption/decryption failed (missing key, tampered file, ...)."""


class EvidenceVault:
    """Encrypts/decrypts evidence media with a box-local AES-256 key."""

    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        if self._key_path.is_file():
            key = self._key_path.read_bytes()
            if len(key) != _KEY_BYTES:
                raise EvidenceCryptoError(
                    f"evidence key at '{self._key_path}' is corrupt "
                    f"({len(key)} bytes, expected {_KEY_BYTES})"
                )
            return key
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(_KEY_BYTES)
        descriptor = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
        return key

    def encrypt_to_file(self, plaintext: bytes, destination: Path) -> int:
        """Encrypt and write; returns the stored size in bytes."""
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = AESGCM(self._key).encrypt(nonce, plaintext, _MAGIC)
        destination.parent.mkdir(parents=True, exist_ok=True)
        blob = _MAGIC + nonce + sealed
        destination.write_bytes(blob)
        return len(blob)

    def decrypt_file(self, source: Path) -> bytes:
        blob = source.read_bytes()
        if len(blob) < len(_MAGIC) + _NONCE_BYTES + 16 or not blob.startswith(_MAGIC):
            raise EvidenceCryptoError(f"'{source.name}' is not a Guardian evidence file")
        nonce = blob[len(_MAGIC) : len(_MAGIC) + _NONCE_BYTES]
        sealed = blob[len(_MAGIC) + _NONCE_BYTES :]
        try:
            return AESGCM(self._key).decrypt(nonce, sealed, _MAGIC)
        except InvalidTag as exc:
            raise EvidenceCryptoError(
                f"'{source.name}' failed integrity check (tampered or wrong key)"
            ) from exc


def secure_delete(path: Path) -> None:
    """Best-effort secure deletion: overwrite with random bytes, then unlink.

    On flash storage wear-leveling may retain older blocks — full-disk
    encryption is the real answer (documented in ADR-0017); this raises the
    bar meanwhile and is required by the retention policy.
    """
    if not path.is_file():
        return
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(secrets.token_bytes(min(size, 1 << 24)))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass  # unlink below is the part that must not fail silently
    path.unlink(missing_ok=True)
