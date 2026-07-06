"""Evidence encryption: AES-256-GCM roundtrip, tamper detection, deletion."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from guardian_edge.infrastructure.evidence.crypto import (
    EvidenceCryptoError,
    EvidenceVault,
    secure_delete,
)


class TestEvidenceVault:
    def test_roundtrip(self, tmp_path: Path) -> None:
        vault = EvidenceVault(tmp_path / "keys" / "evidence.key")
        target = tmp_path / "evidence" / "clip.mp4.enc"
        payload = os.urandom(256_000)
        stored = vault.encrypt_to_file(payload, target)
        assert stored == target.stat().st_size
        assert vault.decrypt_file(target) == payload

    def test_no_plaintext_on_disk(self, tmp_path: Path) -> None:
        vault = EvidenceVault(tmp_path / "evidence.key")
        target = tmp_path / "clip.mp4.enc"
        payload = b"GUARDIAN-PLAINTEXT-MARKER" * 100
        vault.encrypt_to_file(payload, target)
        assert b"GUARDIAN-PLAINTEXT-MARKER" not in target.read_bytes()

    def test_key_is_created_private_and_reused(self, tmp_path: Path) -> None:
        key_path = tmp_path / "keys" / "evidence.key"
        first = EvidenceVault(key_path)
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600, f"key file mode is {oct(mode)}"
        target = tmp_path / "blob.enc"
        first.encrypt_to_file(b"hello", target)
        second = EvidenceVault(key_path)  # restart: same key loads back
        assert second.decrypt_file(target) == b"hello"

    def test_wrong_key_fails_loudly(self, tmp_path: Path) -> None:
        vault_a = EvidenceVault(tmp_path / "a.key")
        vault_b = EvidenceVault(tmp_path / "b.key")
        target = tmp_path / "blob.enc"
        vault_a.encrypt_to_file(b"secret", target)
        with pytest.raises(EvidenceCryptoError, match="integrity"):
            vault_b.decrypt_file(target)

    def test_tampered_file_fails_integrity(self, tmp_path: Path) -> None:
        vault = EvidenceVault(tmp_path / "evidence.key")
        target = tmp_path / "blob.enc"
        vault.encrypt_to_file(b"evidence-bytes", target)
        blob = bytearray(target.read_bytes())
        blob[-1] ^= 0xFF
        target.write_bytes(bytes(blob))
        with pytest.raises(EvidenceCryptoError, match="integrity"):
            vault.decrypt_file(target)

    def test_foreign_blob_is_rejected(self, tmp_path: Path) -> None:
        vault = EvidenceVault(tmp_path / "evidence.key")
        target = tmp_path / "random.bin"
        target.write_bytes(os.urandom(64))
        with pytest.raises(EvidenceCryptoError, match="not a Guardian evidence file"):
            vault.decrypt_file(target)

    def test_corrupt_key_is_refused(self, tmp_path: Path) -> None:
        key_path = tmp_path / "evidence.key"
        key_path.write_bytes(b"short")
        with pytest.raises(EvidenceCryptoError, match="corrupt"):
            EvidenceVault(key_path)


class TestSecureDelete:
    def test_overwrites_then_removes(self, tmp_path: Path) -> None:
        target = tmp_path / "clip.mp4.enc"
        target.write_bytes(b"x" * 1024)
        secure_delete(target)
        assert not target.exists()

    def test_missing_file_is_fine(self, tmp_path: Path) -> None:
        secure_delete(tmp_path / "never-existed")  # must not raise
