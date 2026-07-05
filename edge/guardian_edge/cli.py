"""guardianctl — the operator's command line for a Guardian Edge Box (ADR-0016).

Everything a kindergarten pilot needs after installation, without a
developer: camera setup, diagnostics, health, metrics, backup, restore.

    guardianctl check        validate environment and dependencies
    guardianctl wizard       interactive camera setup (discover / manual / test)
    guardianctl add-camera   non-interactive camera registration
    guardianctl test-camera  probe one configured camera
    guardianctl diagnose     run full diagnostics, write a report
    guardianctl health       show live system health (running box)
    guardianctl metrics      show / export performance metrics (running box)
    guardianctl backup       export configuration archive
    guardianctl restore      import configuration archive
    guardianctl version      print version

All output is also machine-readable (--json where it matters); reports are
written under $GUARDIAN_HOME/reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import yaml

import guardian_edge
from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.ops.backup import BackupError, create_backup, restore_backup
from guardian_edge.ops.diagnostics import run_diagnostics
from guardian_edge.ops.install_check import installation_report, validate_environment
from guardian_edge.ops.monitoring import DEFAULT_HEALTH_PORT
from guardian_edge.ops.paths import GuardianHome

_OK = "✓"
_FAIL = "✗"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    home = (
        GuardianHome.from_env()
        if args.home is None
        else GuardianHome(root=Path(args.home).expanduser())
    )
    try:
        handler = _HANDLERS[args.command]
        return handler(home, args)
    except (GuardianEdgeError, OSError) as exc:
        print(f"{_FAIL} {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guardianctl", description=__doc__.splitlines()[0])
    parser.add_argument("--home", default=None, help="Guardian home (default: $GUARDIAN_HOME)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="validate environment and dependencies")
    sub.add_parser("wizard", help="interactive camera setup")

    add = sub.add_parser("add-camera", help="register a camera non-interactively")
    add.add_argument("--id", required=True, dest="camera_id")
    add.add_argument("--name", required=True)
    add.add_argument("--url", required=True, dest="rtsp_url")
    add.add_argument("--location", default="")
    add.add_argument("--no-test", action="store_true", help="skip the connection probe")

    test = sub.add_parser("test-camera", help="probe one configured camera")
    test.add_argument("camera_id")

    diag = sub.add_parser("diagnose", help="run diagnostics and write a report")
    diag.add_argument("--no-cameras", action="store_true", help="skip live camera probes")
    diag.add_argument("--port", type=int, default=8787, help="device API port to check")

    health = sub.add_parser("health", help="show live system health")
    health.add_argument("--json", action="store_true")
    health.add_argument("--port", type=int, default=DEFAULT_HEALTH_PORT)

    metrics = sub.add_parser("metrics", help="show or export performance metrics")
    metrics.add_argument("--json", action="store_true")
    metrics.add_argument("--export", type=Path, default=None, help="write metrics to a file")
    metrics.add_argument("--port", type=int, default=DEFAULT_HEALTH_PORT)

    backup = sub.add_parser("backup", help="export configuration archive")
    backup.add_argument("destination", nargs="?", type=Path, default=None)

    restore = sub.add_parser("restore", help="import configuration archive")
    restore.add_argument("archive", type=Path)

    sub.add_parser("version", help="print version")
    return parser


# ------------------------------------------------------------- commands


def _cmd_check(home: GuardianHome, args: argparse.Namespace) -> int:
    results = validate_environment(home.root)
    for result in results:
        print(f"  {_OK if result.ok else _FAIL} {result.name}: {result.detail}")
    home.ensure()
    report_path = home.reports_dir / "install-report.json"
    report = installation_report(results, report_path, _now_utc())
    print(f"\nreport: {report_path}")
    if report["ok"]:
        print(f"{_OK} environment ready for Guardian Edge {guardian_edge.__version__}")
        return 0
    print(f"{_FAIL} environment is NOT ready — fix the failed checks above")
    return 1


def _cmd_wizard(home: GuardianHome, args: argparse.Namespace) -> int:
    print("Guardian camera setup wizard")
    print("=" * 40)
    candidates = _discover()
    if candidates:
        print("\nCameras discovered on the network:")
        for index, candidate in enumerate(candidates, 1):
            label = candidate.name or "unknown model"
            print(f"  [{index}] {candidate.address} — {label}")
        print("Discovery only suggests devices; you still provide the RTSP URL.")
    else:
        print("\nNo cameras answered the network probe (manual setup still works).")

    cameras = _load_camera_entries(home)
    while True:
        print(f"\nConfigured cameras: {[c['id'] for c in cameras] or 'none'}")
        answer = input("Add a camera? [y/N] ").strip().lower()
        if answer != "y":
            break
        entry = {
            "id": input("  camera id (e.g. room-1): ").strip(),
            "name": input("  display name: ").strip(),
            "rtsp_url": input("  rtsp url (rtsp://user:pass@ip:554/...): ").strip(),
            "location": input("  location (optional): ").strip(),
        }
        if not entry["id"] or not entry["rtsp_url"]:
            print(f"  {_FAIL} id and rtsp url are required")
            continue
        if any(c["id"] == entry["id"] for c in cameras):
            print(f"  {_FAIL} camera id '{entry['id']}' already exists")
            continue
        if not _probe_entry(entry):
            keep = input("  connection test failed — save anyway? [y/N] ").strip().lower()
            if keep != "y":
                continue
        cameras.append(entry)
        _save_camera_entries(home, cameras)
        print(f"  {_OK} saved to {home.cameras_file}")
    print(f"\n{_OK} wizard finished — {len(cameras)} camera(s) configured")
    return 0


def _cmd_add_camera(home: GuardianHome, args: argparse.Namespace) -> int:
    cameras = _load_camera_entries(home)
    if any(c["id"] == args.camera_id for c in cameras):
        print(f"{_FAIL} camera id '{args.camera_id}' already exists", file=sys.stderr)
        return 1
    entry = {
        "id": args.camera_id,
        "name": args.name,
        "rtsp_url": args.rtsp_url,
        "location": args.location,
    }
    if not args.no_test and not _probe_entry(entry):
        print(f"{_FAIL} connection test failed; use --no-test to save anyway", file=sys.stderr)
        return 1
    cameras.append(entry)
    _save_camera_entries(home, cameras)
    print(f"{_OK} camera '{args.camera_id}' saved to {home.cameras_file}")
    return 0


def _cmd_test_camera(home: GuardianHome, args: argparse.Namespace) -> int:
    from guardian_edge.infrastructure.camera.config import load_cameras

    for camera in load_cameras(home.cameras_file):
        if camera.camera_id == args.camera_id:
            ok = _probe_camera_object(camera)
            return 0 if ok else 1
    print(f"{_FAIL} camera '{args.camera_id}' is not configured", file=sys.stderr)
    return 1


def _cmd_diagnose(home: GuardianHome, args: argparse.Namespace) -> int:
    home.ensure()
    report = run_diagnostics(
        home,
        created_utc=_now_utc(),
        device_api_port=args.port,
        probe_cameras=not args.no_cameras,
    )
    for check in report.checks:
        print(f"  {_OK if check.ok else _FAIL} {check.name}: {check.detail}")
    if report.problems:
        print("\nProblems:")
        for problem in report.problems:
            print(f"  - {problem}")
        print("Recommendations:")
        for recommendation in report.recommendations:
            print(f"  - {recommendation}")
    path = home.reports_dir / "diagnostics-report.json"
    report.save(path)
    print(f"\nreport: {path}")
    ok = all(check.ok for check in report.checks)
    print(f"{_OK} all diagnostics passed" if ok else f"{_FAIL} diagnostics found problems")
    return 0 if ok else 1


def _cmd_health(home: GuardianHome, args: argparse.Namespace) -> int:
    payload = _http_json(f"http://127.0.0.1:{args.port}/health")
    if payload is None:
        print(
            f"{_FAIL} health endpoint unreachable on :{args.port} — is the box running?",
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"status: {payload.get('status')}   version: {payload.get('version')}")
    host = payload.get("host", {})
    print(
        f"cpu {host.get('cpu_percent')}%  ram {host.get('memory_percent')}%  "
        f"disk {host.get('disk_percent')}%  temp {host.get('temperature_c')}°C"
    )
    for name, component in sorted(payload.get("components", {}).items()):
        status = component.get("status", "?") if isinstance(component, dict) else component
        print(f"  {_OK if status == 'ok' else _FAIL} {name}: {status}")
    for source, warning in payload.get("warnings", {}).items():
        print(f"  ! {source}: {warning}")
    return 0


def _cmd_metrics(home: GuardianHome, args: argparse.Namespace) -> int:
    payload = _http_json(f"http://127.0.0.1:{args.port}/metrics")
    if payload is None:
        print(
            f"{_FAIL} metrics endpoint unreachable on :{args.port} — is the box running?",
            file=sys.stderr,
        )
        return 1
    if args.export is not None:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"{_OK} metrics exported to {args.export}")
        return 0
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_backup(home: GuardianHome, args: argparse.Namespace) -> int:
    home.ensure()
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = args.destination or home.backups_dir / f"guardian-backup-{stamp}.zip"
    manifest = create_backup(home, destination, _now_utc())
    print(f"{_OK} backup written: {destination}")
    print(f"  includes: {manifest['files'] or 'nothing yet (fresh box)'}")
    return 0


def _cmd_restore(home: GuardianHome, args: argparse.Namespace) -> int:
    try:
        restored = restore_backup(args.archive, home)
    except BackupError as exc:
        print(f"{_FAIL} {exc}", file=sys.stderr)
        return 1
    print(f"{_OK} restored {len(restored)} file(s): {restored}")
    print("restart the box service to apply the configuration")
    return 0


def _cmd_version(home: GuardianHome, args: argparse.Namespace) -> int:
    print(f"guardian-edge {guardian_edge.__version__}")
    return 0


_HANDLERS = {
    "check": _cmd_check,
    "wizard": _cmd_wizard,
    "add-camera": _cmd_add_camera,
    "test-camera": _cmd_test_camera,
    "diagnose": _cmd_diagnose,
    "health": _cmd_health,
    "metrics": _cmd_metrics,
    "backup": _cmd_backup,
    "restore": _cmd_restore,
    "version": _cmd_version,
}


# -------------------------------------------------------------- helpers


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _discover() -> list[Any]:
    from guardian_edge.infrastructure.camera.discovery import OnvifWsDiscovery

    try:
        return list(OnvifWsDiscovery().discover())
    except GuardianEdgeError:
        return []


def _load_camera_entries(home: GuardianHome) -> list[dict[str, str]]:
    if not home.cameras_file.is_file():
        return []
    raw = yaml.safe_load(home.cameras_file.read_text(encoding="utf-8")) or {}
    return list(raw.get("cameras", []))


def _save_camera_entries(home: GuardianHome, cameras: list[dict[str, str]]) -> None:
    home.cameras_file.parent.mkdir(parents=True, exist_ok=True)
    home.cameras_file.write_text(
        yaml.safe_dump({"cameras": cameras}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _probe_entry(entry: dict[str, str]) -> bool:
    from guardian_edge.domain.camera import Camera

    camera = Camera(
        camera_id=entry["id"],
        name=entry["name"] or entry["id"],
        rtsp_url=entry["rtsp_url"],
        location=entry.get("location", ""),
    )
    return _probe_camera_object(camera)


def _probe_camera_object(camera: Any) -> bool:
    from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory
    from guardian_edge.ops.camera_probe import probe_camera

    print(f"  testing {camera.camera_id} ({camera.redacted_url()}) ...", flush=True)
    result = probe_camera(OpenCvRtspStreamFactory(), camera)
    if result.ok:
        print(
            f"  {_OK} connected: {result.width}x{result.height} "
            f"@ {result.measured_fps} fps ({result.frames_read} frames)"
        )
        return True
    print(f"  {_FAIL} {result.error}")
    return False


def _http_json(url: str) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310 - fixed localhost URL
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
