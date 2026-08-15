"""Fetching: pinned, verified, and refusing everything it cannot vouch for."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.fetch import (
    LOCKFILE_NAME,
    RemoteFile,
    SourceLock,
    SourceSpec,
    fetch_source,
)
from guardian_ai.acquisition.sources import GMDCSA24, URFALL, available_sources, get_source

_PAYLOAD = b"video-bytes"
_DIGEST = hashlib.sha256(_PAYLOAD).hexdigest()


def _opener(bodies: dict[str, bytes]):  # noqa: ANN202 - test helper
    def open_url(url: str) -> io.BytesIO:
        if url not in bodies:
            raise AssertionError(f"unexpected fetch of {url}")
        return io.BytesIO(bodies[url])

    return open_url


def _spec(*files: RemoteFile) -> SourceSpec:
    return SourceSpec(name="test", homepage="https://example.invalid", license_note="", files=files)


@pytest.fixture
def lock(tmp_path: Path) -> SourceLock:
    return SourceLock(tmp_path / LOCKFILE_NAME)


def test_first_fetch_pins_the_digest(tmp_path: Path, lock: SourceLock) -> None:
    spec = _spec(RemoteFile("https://x.invalid/a.mp4", "a.mp4"))
    result = fetch_source(
        spec, tmp_path / "raw", lock, opener=_opener({"https://x.invalid/a.mp4": _PAYLOAD})
    )
    assert result.newly_pinned == ("https://x.invalid/a.mp4",)
    assert (tmp_path / "raw" / "a.mp4").read_bytes() == _PAYLOAD
    written = json.loads((tmp_path / LOCKFILE_NAME).read_text())
    assert written["sha256"]["https://x.invalid/a.mp4"] == _DIGEST


def test_pinned_digest_is_verified_not_repinned(tmp_path: Path, lock: SourceLock) -> None:
    lock.pin("https://x.invalid/a.mp4", _DIGEST)
    result = fetch_source(
        _spec(RemoteFile("https://x.invalid/a.mp4", "a.mp4")),
        tmp_path / "raw",
        lock,
        opener=_opener({"https://x.invalid/a.mp4": _PAYLOAD}),
    )
    assert result.newly_pinned == ()
    assert result.downloaded == ("a.mp4",)


def test_checksum_mismatch_keeps_nothing(tmp_path: Path, lock: SourceLock) -> None:
    """A changed upstream file is a hard stop, and the bytes do not survive
    it — a half-trusted corpus on disk is how the wrong data gets trained on."""
    lock.pin("https://x.invalid/a.mp4", "0" * 64)
    with pytest.raises(AcquisitionError, match="checksum mismatch"):
        fetch_source(
            _spec(RemoteFile("https://x.invalid/a.mp4", "a.mp4")),
            tmp_path / "raw",
            lock,
            opener=_opener({"https://x.invalid/a.mp4": _PAYLOAD}),
        )
    assert not (tmp_path / "raw" / "a.mp4").exists()


def test_existing_files_are_skipped_unless_forced(tmp_path: Path, lock: SourceLock) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.mp4").write_bytes(b"already here")
    spec = _spec(RemoteFile("https://x.invalid/a.mp4", "a.mp4"))
    assert fetch_source(spec, raw, lock, opener=_opener({})).skipped == ("a.mp4",)

    forced = fetch_source(
        spec, raw, lock, force=True, opener=_opener({"https://x.invalid/a.mp4": _PAYLOAD})
    )
    assert forced.downloaded == ("a.mp4",)
    assert (raw / "a.mp4").read_bytes() == _PAYLOAD


def test_zip_is_extracted_and_the_archive_removed(tmp_path: Path, lock: SourceLock) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("fall-01-cam0/frame_0001.png", "pixels")
    fetch_source(
        _spec(RemoteFile("https://x.invalid/f.zip", "videos/f.zip", extract=True)),
        tmp_path / "raw",
        lock,
        opener=_opener({"https://x.invalid/f.zip": buffer.getvalue()}),
    )
    assert (tmp_path / "raw" / "videos" / "fall-01-cam0" / "frame_0001.png").is_file()
    assert not (tmp_path / "raw" / "videos" / "f.zip").exists()


def test_tarball_strip_root_lands_the_dataset_at_the_top(tmp_path: Path, lock: SourceLock) -> None:
    """GitHub wraps everything in <repo>-<ref>/; the importer expects
    'Subject 1/…' directly under the raw directory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        info = tarfile.TarInfo("repo-master/Subject 1/Fall.csv")
        info.size = len(_PAYLOAD)
        tf.addfile(info, io.BytesIO(_PAYLOAD))
    fetch_source(
        _spec(RemoteFile("https://x.invalid/r.tar.gz", "r.tar.gz", extract=True, strip_root=True)),
        tmp_path / "raw",
        lock,
        opener=_opener({"https://x.invalid/r.tar.gz": buffer.getvalue()}),
    )
    assert (tmp_path / "raw" / "Subject 1" / "Fall.csv").read_bytes() == _PAYLOAD


def test_escaping_archive_paths_are_refused(tmp_path: Path, lock: SourceLock) -> None:
    """An archive off the network is untrusted input even from a reputable
    host, and one '../' entry writes outside the raw directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../escaped.txt", "nope")
    with pytest.raises(AcquisitionError, match="escaping path"):
        fetch_source(
            _spec(RemoteFile("https://x.invalid/e.zip", "e.zip", extract=True)),
            tmp_path / "raw",
            lock,
            opener=_opener({"https://x.invalid/e.zip": buffer.getvalue()}),
        )


def test_strip_root_refuses_an_ambiguous_archive(tmp_path: Path, lock: SourceLock) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("one/a.txt", "a")
        zf.writestr("two/b.txt", "b")
    with pytest.raises(AcquisitionError, match="exactly one top-level"):
        fetch_source(
            _spec(RemoteFile("https://x.invalid/m.zip", "m.zip", extract=True, strip_root=True)),
            tmp_path / "raw",
            lock,
            opener=_opener({"https://x.invalid/m.zip": buffer.getvalue()}),
        )


def test_lock_roundtrips(tmp_path: Path) -> None:
    lock = SourceLock(tmp_path / LOCKFILE_NAME)
    lock.pin("https://x.invalid/a", _DIGEST)
    lock.save()
    assert SourceLock(tmp_path / LOCKFILE_NAME).expected("https://x.invalid/a") == _DIGEST


# ------------------------------------------------------------ source specs


def test_available_sources() -> None:
    assert available_sources() == ["gmdcsa24", "urfall"]


def test_unknown_source_explains_the_manual_path() -> None:
    with pytest.raises(AcquisitionError, match="downloaded by hand"):
        get_source("le2i")


def test_urfall_spec_covers_every_sequence_and_both_label_files() -> None:
    targets = [f.target for f in URFALL.files]
    assert "urfall-cam0-falls.csv" in targets
    assert "urfall-cam0-adls.csv" in targets
    assert sum(1 for t in targets if t.startswith("videos/fall-")) == 30
    assert sum(1 for t in targets if t.startswith("videos/adl-")) == 40
    assert all(f.url.startswith("http://fenix.ur.edu.pl/") for f in URFALL.files)


def test_gmdcsa24_spec_strips_the_github_wrapper() -> None:
    (archive,) = GMDCSA24.files
    assert archive.extract and archive.strip_root


def test_a_spec_must_list_files() -> None:
    with pytest.raises(AcquisitionError, match="no files"):
        SourceSpec(name="empty", homepage="", license_note="")
