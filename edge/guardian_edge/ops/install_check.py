"""Environment and dependency validation for the installer (ADR-0016).

Every check is machine-readable; the installer refuses to proceed on
failed requirements and records everything in the installation report.
"""

from __future__ import annotations

import json
import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

import guardian_edge
from guardian_edge.ops.clock import local_timezone_name

MIN_PYTHON = (3, 10)
MIN_FREE_DISK_GB = 5.0
MIN_RAM_GB = 2.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def validate_environment(home: Path) -> list[CheckResult]:
    """Run every environment/dependency check."""
    return [
        _python_version(),
        _dependencies(),
        _disk(home),
        _memory(),
        _network(),
        _writable(home),
        _timezone(),
    ]


def installation_report(
    results: list[CheckResult], report_path: Path, created_utc: str
) -> dict[str, Any]:
    """Write the machine-readable installation report; returns it."""
    report = {
        "created_utc": created_utc,
        "guardian_edge_version": guardian_edge.__version__,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "checks": [asdict(result) for result in results],
        "ok": all(result.ok for result in results if result.required),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _python_version() -> CheckResult:
    ok = sys.version_info[:2] >= MIN_PYTHON
    return CheckResult(
        "python_version",
        ok,
        f"{sys.version.split()[0]} (minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
    )


def _dependencies() -> CheckResult:
    missing = []
    for module in ("cv2", "numpy", "onnxruntime", "websockets", "yaml", "psutil"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    ffmpeg_ok = False
    if "cv2" not in missing:
        import cv2

        ffmpeg_ok = "FFMPEG" in cv2.getBuildInformation() or shutil.which("ffmpeg") is not None
    detail = "all runtime dependencies importable" if not missing else f"missing: {missing}"
    if not ffmpeg_ok:
        missing.append("ffmpeg (RTSP backend)")
        detail = f"missing: {missing}"
    return CheckResult("dependencies", not missing, detail)


def _disk(home: Path) -> CheckResult:
    target = home if home.exists() else home.parent if home.parent.exists() else Path.home()
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1 << 30)
    return CheckResult(
        "disk_space",
        free_gb >= MIN_FREE_DISK_GB,
        f"{free_gb:.1f} GB free (minimum {MIN_FREE_DISK_GB:.0f} GB)",
    )


def _memory() -> CheckResult:
    total_gb = psutil.virtual_memory().total / (1 << 30)
    return CheckResult(
        "memory", total_gb >= MIN_RAM_GB, f"{total_gb:.1f} GB RAM (minimum {MIN_RAM_GB:.0f} GB)"
    )


def _network() -> CheckResult:
    """A LAN-reachable address must exist — phones need to find this box."""
    addresses = []
    for interface_addresses in psutil.net_if_addrs().values():
        for address in interface_addresses:
            if address.family == socket.AF_INET and not address.address.startswith("127."):
                addresses.append(address.address)
    return CheckResult(
        "network",
        bool(addresses),
        f"LAN addresses: {addresses}" if addresses else "no non-loopback IPv4 address",
    )


def _timezone() -> CheckResult:
    """A configured local timezone (ADR-0018 §8).

    Not required: at install time nobody knows yet whether this box will
    get safe-area zones with hours, and blocking an install over a feature
    that may never be used is the wrong trade. It is surfaced loudly
    because the failure it prevents is quiet — a nap-room boundary
    enforced at the wrong hour, or (fail-safe) around the clock.
    """
    name = local_timezone_name()
    if name:
        return CheckResult("timezone", True, name, required=False)
    return CheckResult(
        "timezone",
        False,
        "no local timezone configured — scheduled safe areas will be enforced "
        "around the clock until one is set (see ADR-0018)",
        required=False,
    )


def _writable(home: Path) -> CheckResult:
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult("home_writable", True, str(home))
    except OSError as exc:
        return CheckResult("home_writable", False, f"{home}: {exc}")
