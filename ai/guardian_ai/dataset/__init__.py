"""Dataset platform CLI: ``python -m guardian_ai.dataset <command>``.

The whole mandated lifecycle from one entry point:

    fetch -> import -> annotate -> validate -> review -> publish -> report/statistics

plus ``import-pilot`` for Guardian Edge evidence. Every command works on
a workspace directory (guardian_dataset_v1) or the registry — no hidden
state, no manual dataset manipulation.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.fetch import LOCKFILE_NAME, SourceLock, fetch_source
from guardian_ai.acquisition.importers import available_importers, get_importer
from guardian_ai.acquisition.importers.base import run_import
from guardian_ai.acquisition.pilot import import_pilot_evidence
from guardian_ai.acquisition.privacy import check_privacy
from guardian_ai.acquisition.quality import validate_quality, write_quality_report
from guardian_ai.acquisition.registry import VideoDatasetRegistry
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.sources import available_sources, get_source
from guardian_ai.acquisition.statistics import compute_statistics, generate_dataset_report
from guardian_ai.acquisition.workspace import DatasetWorkspace, WorkspaceManifest

logger = logging.getLogger(__name__)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def _open_or_create_workspace(arguments: argparse.Namespace) -> DatasetWorkspace:
    root = Path(arguments.workspace)
    if (root / "dataset.json").is_file():
        return DatasetWorkspace.open(root)
    manifest = WorkspaceManifest(
        name=arguments.name,
        description=arguments.description,
        collected_by=arguments.collected_by,
        consent_reference=arguments.consent,
        contains_minors=False,  # open research datasets: adult volunteers
        anonymized=True,
        license="Proprietary-GuardianAI",
    )
    return DatasetWorkspace.create(root, manifest)


# ------------------------------------------------------------------ commands


def cmd_fetch(arguments: argparse.Namespace) -> int:
    spec = get_source(arguments.source)
    lock = SourceLock(Path(arguments.lockfile))
    result = fetch_source(spec, Path(arguments.raw), lock, force=arguments.force)
    payload = result.to_dict()
    payload["homepage"] = spec.homepage
    payload["license_note"] = spec.license_note
    if result.newly_pinned:
        payload["warning"] = (
            f"{len(result.newly_pinned)} URL(s) had no pinned checksum and were "
            f"recorded on trust — review the {LOCKFILE_NAME} diff before committing"
        )
    _print(payload)
    return 0


def cmd_import(arguments: argparse.Namespace) -> int:
    importer = get_importer(arguments.source)
    workspace = _open_or_create_workspace(arguments)
    result = run_import(importer, Path(arguments.raw), workspace)
    _print(
        {
            "source": result.source,
            "imported": len(result.imported),
            "clips": result.splits,
            "workspace": str(workspace.root),
            "review_state": ReviewWorkflow(workspace.root).state().value,  # type: ignore[union-attr]
        }
    )
    return 0


def cmd_import_pilot(arguments: argparse.Namespace) -> int:
    workspace = _open_or_create_workspace(arguments)
    imported = import_pilot_evidence(Path(arguments.evidence), workspace)
    lineage = {clip_id: workspace.metadata(clip_id)["lineage"] for clip_id in imported}
    _print(
        {
            "imported": imported,
            "lineage": lineage,
            "note": "candidates only — annotation and review required, no automatic publication",
        }
    )
    return 0


def cmd_annotate(arguments: argparse.Namespace) -> int:
    from guardian_ai.acquisition.annotator.server import AnnotatorServer
    from guardian_ai.acquisition.annotator.session import AnnotationSession

    workspace = DatasetWorkspace.open(Path(arguments.workspace))
    session = AnnotationSession(workspace, arguments.clip)
    server = AnnotatorServer(session, port=arguments.port)
    print(f"annotator: {server.url}  (clip {arguments.clip}, Ctrl-C to stop)")
    if arguments.open_browser:
        import webbrowser

        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        session.save()
        print("saved — bye")
    return 0


def cmd_validate(arguments: argparse.Namespace) -> int:
    workspace = DatasetWorkspace.open(Path(arguments.workspace))
    quality = validate_quality(workspace)
    report_path = write_quality_report(quality, workspace)
    privacy = check_privacy(workspace)
    _print(
        {
            "quality_ok": quality.ok,
            "quality_errors": [
                {"clip": issue.clip_id, "message": issue.message} for issue in quality.errors
            ],
            "quality_warnings": len(quality.warnings),
            "privacy_ok": privacy.ok,
            "privacy_violations": [
                {"where": violation.where, "message": violation.message}
                for violation in privacy.violations
            ],
            "report": str(report_path),
        }
    )
    return 0 if quality.ok and privacy.ok else 1


def cmd_review(arguments: argparse.Namespace) -> int:
    workflow = ReviewWorkflow(Path(arguments.workspace))
    workflow.record(ReviewState(arguments.to), by=arguments.by, notes=arguments.notes)
    _print(
        {
            "state": workflow.state().value,  # type: ignore[union-attr]
            "history": workflow.history(),
        }
    )
    return 0


def cmd_publish(arguments: argparse.Namespace) -> int:
    workspace = DatasetWorkspace.open(Path(arguments.workspace))
    registry = VideoDatasetRegistry(Path(arguments.registry))
    destination = registry.publish(workspace, arguments.name, arguments.version)
    manifest = registry.version_manifest(arguments.name, arguments.version)
    _print(
        {
            "published": str(destination),
            "approved_by": manifest["approved_by"],
            "videos": manifest["statistics"]["videos"],
            "training_ready": str(destination / "training" / "data.yaml"),
        }
    )
    return 0


def cmd_report(arguments: argparse.Namespace) -> int:
    workspace = DatasetWorkspace.open(Path(arguments.workspace))
    path = generate_dataset_report(workspace)
    _print({"written": str(path)})
    return 0


def cmd_statistics(arguments: argparse.Namespace) -> int:
    workspace = DatasetWorkspace.open(Path(arguments.workspace))
    _print(compute_statistics(workspace))
    return 0


# --------------------------------------------------------------------- main


def _add_workspace_creation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True, help="guardian_dataset_v1 directory")
    parser.add_argument("--name", default="guardian-dataset")
    parser.add_argument("--description", default="Guardian fall-safety video dataset")
    parser.add_argument("--collected-by", dest="collected_by", default="Guardian AI data team")
    parser.add_argument(
        "--consent",
        default="",
        help="consent reference (required by the privacy gate before publish)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m guardian_ai.dataset",
        description="Guardian Dataset Platform (Sprint 18)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="download an open dataset, checksum-pinned")
    fetch.add_argument("source", choices=available_sources())
    fetch.add_argument("--raw", required=True, help="raw dataset directory to fill")
    fetch.add_argument(
        "--lockfile",
        default=LOCKFILE_NAME,
        help=f"checksum lockfile, committed to the repo (default: {LOCKFILE_NAME})",
    )
    fetch.add_argument("--force", action="store_true", help="re-download files already on disk")
    fetch.set_defaults(handler=cmd_fetch)

    import_parser = commands.add_parser("import", help="import an open dataset")
    import_parser.add_argument("source", choices=available_importers())
    import_parser.add_argument("--raw", required=True, help="raw dataset directory")
    _add_workspace_creation(import_parser)
    import_parser.set_defaults(handler=cmd_import)

    pilot = commands.add_parser("import-pilot", help="import Guardian Edge evidence")
    pilot.add_argument("--evidence", required=True, help="decrypted evidence export dir")
    _add_workspace_creation(pilot)
    pilot.set_defaults(handler=cmd_import_pilot)

    annotate = commands.add_parser("annotate", help="open the local annotation editor")
    annotate.add_argument("--workspace", required=True)
    annotate.add_argument("--clip", required=True)
    annotate.add_argument("--port", type=int, default=8765)
    annotate.add_argument("--no-browser", dest="open_browser", action="store_false")
    annotate.set_defaults(handler=cmd_annotate)

    validate = commands.add_parser("validate", help="quality + privacy gates")
    validate.add_argument("--workspace", required=True)
    validate.set_defaults(handler=cmd_validate)

    review = commands.add_parser("review", help="advance the review workflow")
    review.add_argument("--workspace", required=True)
    review.add_argument(
        "--to",
        required=True,
        choices=[state.value for state in ReviewState if state is not ReviewState.PUBLISHED],
    )
    review.add_argument("--by", required=True, help="named reviewer")
    review.add_argument("--notes", default="")
    review.set_defaults(handler=cmd_review)

    publish = commands.add_parser("publish", help="publish an APPROVED workspace")
    publish.add_argument("--workspace", required=True)
    publish.add_argument("--registry", required=True)
    publish.add_argument("--name", required=True)
    publish.add_argument("--version", required=True, help="MAJOR.MINOR.PATCH")
    publish.set_defaults(handler=cmd_publish)

    report = commands.add_parser("report", help="generate dataset-report.pdf")
    report.add_argument("--workspace", required=True)
    report.set_defaults(handler=cmd_report)

    statistics = commands.add_parser("statistics", help="print dataset statistics JSON")
    statistics.add_argument("--workspace", required=True)
    statistics.set_defaults(handler=cmd_statistics)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
