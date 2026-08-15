"""Fetching open datasets — reproducibly, or not at all.

A dataset downloaded by hand has no provenance. Nobody can say later which
bytes trained the model, whether the host changed them, or whether two
engineers on two machines got the same corpus. ADR-0010 demands the whole
chain from source to model; a manual `wget` breaks it at the first link.

So fetching is a command, and every byte it accepts is pinned:

- The **source spec** lists the exact URLs the dataset publishes.
- A **lockfile** (``dataset-sources.lock.json``, committed to the repo)
  records each file's sha256. It is reviewed like code.
- On the first fetch of an unpinned file the digest is computed and
  written to the lockfile — trust on first use, stated plainly rather than
  hidden. Every fetch after that verifies, and a mismatch is a hard error.

Pinning digests by hand was considered and rejected: a checksum invented by
someone who never downloaded the file fails every fetch and looks exactly
like corruption. Better to record what actually arrived and let the review
of the lockfile diff be the human check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from guardian_ai.acquisition.errors import AcquisitionError

logger = logging.getLogger(__name__)

LOCKFILE_NAME = "dataset-sources.lock.json"
_CHUNK_BYTES = 1 << 20
_USER_AGENT = "guardian-ai-dataset-fetch/1.0"


class _ByteStream(Protocol):
    """What ``urlopen`` returns, and what a test opener has to provide."""

    def read(self, size: int = ...) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One file the dataset publishes, and where it lands."""

    url: str
    target: str
    """Path under the raw directory. Directories are created as needed."""

    extract: bool = False
    """Unpack into ``target``'s parent instead of keeping the archive."""

    strip_root: bool = False
    """Drop the archive's single top-level directory while extracting.

    GitHub tarballs wrap everything in ``<repo>-<ref>/``; the importer
    expects the dataset's own layout at the top."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Everything needed to reconstruct one raw dataset directory."""

    name: str
    homepage: str
    license_note: str
    files: tuple[RemoteFile, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.files:
            raise AcquisitionError(f"source '{self.name}' lists no files to fetch")


@dataclass(frozen=True, slots=True)
class FetchResult:
    source: str
    raw_dir: Path
    downloaded: tuple[str, ...]
    skipped: tuple[str, ...]
    newly_pinned: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "raw_dir": str(self.raw_dir),
            "downloaded": list(self.downloaded),
            "already_present": list(self.skipped),
            "newly_pinned": list(self.newly_pinned),
        }


class SourceLock:
    """The committed record of which bytes each URL is allowed to return."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._digests: dict[str, str] = {}
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._digests = {str(k): str(v) for k, v in raw.get("sha256", {}).items()}

    def expected(self, url: str) -> str | None:
        return self._digests.get(url)

    def pin(self, url: str, digest: str) -> None:
        self._digests[url] = digest

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "comment": (
                        "sha256 per source URL. Pinned on first fetch and verified on "
                        "every fetch after. Review changes here as carefully as code: "
                        "a changed digest means the upstream file changed."
                    ),
                    "sha256": dict(sorted(self._digests.items())),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def fetch_source(
    spec: SourceSpec,
    raw_dir: Path,
    lock: SourceLock,
    *,
    force: bool = False,
    opener: Callable[[str], _ByteStream] | None = None,
) -> FetchResult:
    """Download and verify every file of one source into ``raw_dir``."""
    downloaded: list[str] = []
    skipped: list[str] = []
    newly_pinned: list[str] = []
    raw_dir.mkdir(parents=True, exist_ok=True)
    for remote in spec.files:
        destination = raw_dir / remote.target
        if destination.exists() and not force:
            skipped.append(remote.target)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = _download(remote.url, destination, opener)
        expected = lock.expected(remote.url)
        if expected is None:
            lock.pin(remote.url, digest)
            newly_pinned.append(remote.url)
            logger.warning(
                "fetch: %s was not pinned; recorded sha256 %s — review the lockfile diff",
                remote.url,
                digest,
            )
        elif expected != digest:
            destination.unlink(missing_ok=True)
            raise AcquisitionError(
                f"checksum mismatch for {remote.url}: lockfile says {expected}, "
                f"got {digest}. The upstream file changed, or the download was "
                f"tampered with. Nothing was kept."
            )
        if remote.extract:
            _extract(destination, remote.strip_root)
            destination.unlink()
        downloaded.append(remote.target)
    if newly_pinned:
        lock.save()
    return FetchResult(
        source=spec.name,
        raw_dir=raw_dir,
        downloaded=tuple(downloaded),
        skipped=tuple(skipped),
        newly_pinned=tuple(newly_pinned),
    )


def _download(url: str, destination: Path, opener: Callable[[str], _ByteStream] | None) -> str:
    """Stream to disk, hashing as it goes. Returns the sha256."""
    digest = hashlib.sha256()
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    try:
        response: _ByteStream = (
            opener(url) if opener else urllib.request.urlopen(request)  # noqa: S310
        )
    except urllib.error.URLError as exc:
        raise AcquisitionError(f"cannot fetch {url}: {exc}") from exc
    try:
        with partial.open("wb") as handle:
            while chunk := response.read(_CHUNK_BYTES):
                digest.update(chunk)
                handle.write(chunk)
    finally:
        response.close()
    partial.replace(destination)
    return digest.hexdigest()


def _extract(archive: Path, strip_root: bool) -> None:
    destination = archive.parent
    staging = destination / f".extract-{archive.stem}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                _check_members(zf.namelist(), archive)
                zf.extractall(staging)  # noqa: S202 - members checked above
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                _check_members(tf.getnames(), archive)
                tf.extractall(staging, filter="data")  # noqa: S202 - members checked
        else:
            raise AcquisitionError(f"{archive.name} is neither a zip nor a tar archive")
        root = staging
        if strip_root:
            entries = list(staging.iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise AcquisitionError(
                    f"{archive.name}: strip_root expects exactly one top-level "
                    f"directory, found {len(entries)}"
                )
            root = entries[0]
        for entry in root.iterdir():
            target = destination / entry.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            entry.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _check_members(names: list[str], archive: Path) -> None:
    """Refuse path traversal before unpacking anything.

    An archive fetched over the network is untrusted input even when the
    host is reputable, and one `../` entry writes outside the raw directory.
    """
    for name in names:
        if name.startswith("/") or ".." in Path(name).parts:
            raise AcquisitionError(f"{archive.name} contains an escaping path: '{name}'")
