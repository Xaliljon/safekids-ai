"""Training platform CLI: ``python -m guardian_ai.train <command>``.

One entry point drives the whole workflow the platform guarantees:

    Dataset -> train -> evaluate -> export -> benchmark -> report
            -> compare -> promote (manual approval only)

Every command works on a run directory (the experiment's isolated home),
so nothing here has hidden state: what the CLI reads is what is on disk.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from guardian_ai.evaluation.detection import EVALUATION_FILE, save_evaluation
from guardian_ai.evaluation.error_analysis import (
    ERROR_ANALYSIS_FILE,
    analyze_errors,
    save_error_analysis,
)
from guardian_ai.export.compat import check_compatibility
from guardian_ai.export.manifest import build_manifest, load_manifest, save_manifest
from guardian_ai.export.onnx_export import MODEL_FILE, export_onnx
from guardian_ai.training.coco_baseline import evaluate_coco_baseline, fetch_official_checkpoint
from guardian_ai.training.compare import (
    COMPARISON_FILE,
    benchmark_onnx,
    compare_models,
    save_comparison,
)
from guardian_ai.training.config import TrainingConfig, config_from_dict, load_config
from guardian_ai.training.engine import Trainer
from guardian_ai.training.errors import TrainingError
from guardian_ai.training.experiment import Experiment
from guardian_ai.training.promote import promote
from guardian_ai.training.qualitative import QUALITATIVE_DIR, export_qualitative_samples
from guardian_ai.training.reports import generate_reports, load_history
from guardian_ai.training.video_data import VideoRegistryDataModule

logger = logging.getLogger(__name__)


def _config_for_run(experiment: Experiment) -> TrainingConfig:
    return config_from_dict(
        dict(experiment.record["config"]),
        source=str(experiment.run_dir / "experiment.json"),
    )


def _open_run(run_dir: Path) -> tuple[Experiment, Trainer]:
    experiment = Experiment.load(run_dir)
    return experiment, Trainer(_config_for_run(experiment))


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


# ------------------------------------------------------------------ commands


def cmd_train(arguments: argparse.Namespace) -> int:
    config = load_config(Path(arguments.config))
    experiment = Trainer(config).train()
    _print(
        {
            "experiment_id": experiment.experiment_id,
            "run_dir": str(experiment.run_dir),
            "status": experiment.record["status"],
            "epochs_completed": experiment.record["epochs_completed"],
            "metrics": experiment.record["metrics"],
        }
    )
    return 0


def cmd_resume(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run)
    experiment, trainer = _open_run(run_dir)
    experiment = trainer.resume(run_dir)
    _print(
        {
            "experiment_id": experiment.experiment_id,
            "status": experiment.record["status"],
            "epochs_completed": experiment.record["epochs_completed"],
            "metrics": experiment.record["metrics"],
        }
    )
    return 0


def cmd_evaluate(arguments: argparse.Namespace) -> int:
    experiment, trainer = _open_run(Path(arguments.run))
    config = _config_for_run(experiment)
    split = arguments.split or config.dataset.test_split
    model = trainer.load_best_model(experiment)
    evaluation = trainer.evaluate(model, split)
    destination = experiment.reports_dir / EVALUATION_FILE
    save_evaluation(evaluation, destination)
    experiment.update(evaluated_split=split)
    _print({"split": split, "written": str(destination), "overall": evaluation["overall"]})
    return 0


def cmd_export(arguments: argparse.Namespace) -> int:
    import torch

    experiment, trainer = _open_run(Path(arguments.run))
    config = _config_for_run(experiment)
    family = trainer.family
    model = trainer.load_best_model(experiment)
    destination = experiment.export_dir / MODEL_FILE
    sha256 = export_onnx(model, family, config.model.input_size, destination)
    experiment.set_checksum(MODEL_FILE, sha256)

    with torch.no_grad():
        output_shape = list(
            model(torch.zeros(1, 3, config.model.input_size, config.model.input_size)).shape
        )
    manifest = build_manifest(
        model_name=arguments.name or family.name,
        model_version=arguments.version,
        sha256=sha256,
        labels=trainer.data.class_names,
        license_id=family.license,
        input_name=family.input_name(),
        output_name=family.output_name(),
        input_shape=[1, 3, config.model.input_size, config.model.input_size],
        output_shape=output_shape,
        dataset_name=experiment.record["dataset"]["name"],
        dataset_version=experiment.record["dataset"]["version"],
        taxonomy_name=experiment.record["taxonomy"]["name"],
        taxonomy_version=experiment.record["taxonomy"]["version"],
        experiment_id=experiment.experiment_id,
        git_commit=experiment.record["git_commit"],
    )
    manifest_path = save_manifest(manifest, experiment.export_dir)
    passed = check_compatibility(destination, manifest)
    _print(
        {
            "model": str(destination),
            "manifest": str(manifest_path),
            "sha256": sha256,
            "compatibility": passed,
        }
    )
    return 0


def cmd_benchmark(arguments: argparse.Namespace) -> int:
    experiment, _ = _open_run(Path(arguments.run))
    model_path = experiment.export_dir / MODEL_FILE
    manifest = load_manifest(experiment.export_dir)
    result = benchmark_onnx(
        model_path,
        input_name=manifest["inputs"][0]["name"],
        input_shape=tuple(manifest["inputs"][0]["shape"]),
        runs=arguments.runs,
    )
    experiment.update(benchmark=result.to_dict())
    _print(result.to_dict())
    return 0


def cmd_report(arguments: argparse.Namespace) -> int:
    experiment, _ = _open_run(Path(arguments.run))
    evaluation_path = experiment.reports_dir / EVALUATION_FILE
    if not evaluation_path.is_file():
        raise TrainingError(
            f"no {EVALUATION_FILE} in {experiment.reports_dir} — run 'evaluate' first"
        )
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    written = generate_reports(
        evaluation,
        load_history(experiment.run_dir),
        experiment.reports_dir,
        title=experiment.experiment_id,
    )
    _print({"written": [str(path) for path in written]})
    return 0


def cmd_compare(arguments: argparse.Namespace) -> int:
    candidate, _ = _open_run(Path(arguments.candidate))
    baseline, _ = _open_run(Path(arguments.baseline))

    def load_side(experiment: Experiment) -> tuple[dict[str, Any], Any]:
        evaluation_path = experiment.reports_dir / EVALUATION_FILE
        if not evaluation_path.is_file():
            raise TrainingError(
                f"{experiment.experiment_id}: no {EVALUATION_FILE} — run 'evaluate' first"
            )
        manifest = load_manifest(experiment.export_dir)
        bench = benchmark_onnx(
            experiment.export_dir / MODEL_FILE,
            input_name=manifest["inputs"][0]["name"],
            input_shape=tuple(manifest["inputs"][0]["shape"]),
            runs=arguments.runs,
        )
        return json.loads(evaluation_path.read_text(encoding="utf-8")), bench

    candidate_eval, candidate_bench = load_side(candidate)
    baseline_eval, baseline_bench = load_side(baseline)
    result = compare_models(candidate_eval, baseline_eval, candidate_bench, baseline_bench)
    result["candidate_id"] = candidate.experiment_id
    result["baseline_id"] = baseline.experiment_id
    destination = candidate.run_dir / COMPARISON_FILE
    save_comparison(result, destination)
    _print(
        {
            "verdict": result["verdict"],
            "reasons": result["reasons"],
            "written": str(destination),
        }
    )
    return 0 if result["verdict"] == "PROMOTE" else 3


def cmd_promote(arguments: argparse.Namespace) -> int:
    experiment, _ = _open_run(Path(arguments.run))
    destination = promote(
        experiment,
        zoo_root=Path(arguments.zoo),
        approved_by=arguments.approved_by,
    )
    _print(
        {
            "promoted_to": str(destination),
            "approved_by": experiment.record["promotion"]["approved_by"],
            "note": "activation on a box remains a manual guardianctl step",
        }
    )
    return 0


def cmd_error_analysis(arguments: argparse.Namespace) -> int:
    experiment, trainer = _open_run(Path(arguments.run))
    config = _config_for_run(experiment)
    split = arguments.split or config.dataset.test_split
    model = trainer.load_best_model(experiment)
    predictions, ground_truths, paths = trainer.predict_split(model, split)
    result = analyze_errors(
        predictions, ground_truths, paths, trainer.data.class_names, top_k=arguments.top_k
    )
    destination = experiment.reports_dir / ERROR_ANALYSIS_FILE
    save_error_analysis(result, destination)
    _print(
        {
            "split": split,
            "written": str(destination),
            "images_analyzed": result["images_analyzed"],
            "top_false_positive_images": len(result["top_false_positive_images"]),
            "top_false_negative_images": len(result["top_false_negative_images"]),
            "most_confused_classes": result["most_confused_classes"][:5],
        }
    )
    return 0


def cmd_qualitative(arguments: argparse.Namespace) -> int:
    experiment, trainer = _open_run(Path(arguments.run))
    config = _config_for_run(experiment)
    if not isinstance(trainer.data, VideoRegistryDataModule):
        raise TrainingError(
            "qualitative export needs dataset.format: video (Sprint 18 training export) — "
            f"this run used format '{config.dataset.format}'"
        )
    split = arguments.split or config.dataset.val_split
    model = trainer.load_best_model(experiment)
    destination = experiment.reports_dir / QUALITATIVE_DIR
    written = export_qualitative_samples(
        model,
        trainer.family,
        trainer.data,
        split,
        destination,
        count=arguments.count,
        seed=arguments.seed,
    )
    _print({"split": split, "written": len(written), "directory": str(destination)})
    return 0


def cmd_coco_compare(arguments: argparse.Namespace) -> int:
    experiment, trainer = _open_run(Path(arguments.run))
    config = _config_for_run(experiment)
    if not isinstance(trainer.data, VideoRegistryDataModule):
        raise TrainingError(
            "coco-compare needs dataset.format: video (Sprint 18 training export) — "
            f"this run used format '{config.dataset.format}'"
        )
    evaluation_path = experiment.reports_dir / EVALUATION_FILE
    if not evaluation_path.is_file():
        raise TrainingError(f"no {EVALUATION_FILE} — run 'evaluate' first")
    manifest = load_manifest(experiment.export_dir)
    candidate_eval = json.loads(evaluation_path.read_text(encoding="utf-8"))
    candidate_bench = benchmark_onnx(
        experiment.export_dir / MODEL_FILE,
        input_name=manifest["inputs"][0]["name"],
        input_shape=tuple(manifest["inputs"][0]["shape"]),
        runs=arguments.runs,
    )

    split = arguments.split or config.dataset.test_split
    onnx_path = fetch_official_checkpoint(
        Path(arguments.zoo_root), Path(arguments.edge_project_root)
    )
    coco_eval = evaluate_coco_baseline(onnx_path, trainer.data, split)
    coco_bench = benchmark_onnx(
        onnx_path, input_name="images", input_shape=(1, 3, 416, 416), runs=arguments.runs
    )

    result = compare_models(candidate_eval, coco_eval, candidate_bench, coco_bench)
    result["candidate_id"] = experiment.experiment_id
    result["baseline_id"] = "yolox-tiny-coco-0.1.1-rc0"
    destination = experiment.run_dir / "coco-comparison.json"
    save_comparison(result, destination)
    _print(
        {
            "verdict": result["verdict"],
            "reasons": result["reasons"],
            "written": str(destination),
            "candidate_precision": candidate_eval["overall"]["precision"],
            "coco_precision": coco_eval["overall"]["precision"],
        }
    )
    return 0


def cmd_candidate(arguments: argparse.Namespace) -> int:
    """Mark a run as a CANDIDATE model. Never installs into any model
    zoo — Sprint 19 rule: 'DO NOT deploy. Candidate Model Only.'"""
    experiment, _ = _open_run(Path(arguments.run))
    experiment.update(
        candidate={
            "status": "candidate",
            "not_production": True,
            "notes": arguments.notes,
        }
    )
    _print(
        {
            "experiment_id": experiment.experiment_id,
            "status": "candidate",
            "note": "not installed into any model zoo — promotion is a separate, "
            "later, human decision",
        }
    )
    return 0


# --------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m guardian_ai.train",
        description="Guardian AI training platform (Sprint 17)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    train = commands.add_parser("train", help="train from a YAML config")
    train.add_argument("--config", required=True, help="path to training YAML")
    train.set_defaults(handler=cmd_train)

    resume = commands.add_parser("resume", help="continue an interrupted run")
    resume.add_argument("--run", required=True, help="run directory")
    resume.set_defaults(handler=cmd_resume)

    evaluate = commands.add_parser("evaluate", help="full metric set on a split")
    evaluate.add_argument("--run", required=True)
    evaluate.add_argument("--split", default=None, help="default: the config's test split")
    evaluate.set_defaults(handler=cmd_evaluate)

    export = commands.add_parser(
        "export", help="ONNX export + validation + auto manifest + compatibility check"
    )
    export.add_argument("--run", required=True)
    export.add_argument("--version", required=True, help="model version, e.g. 0.1.0")
    export.add_argument("--name", default=None, help="zoo model name (default: family)")
    export.set_defaults(handler=cmd_export)

    benchmark = commands.add_parser("benchmark", help="latency/memory/size of the export")
    benchmark.add_argument("--run", required=True)
    benchmark.add_argument("--runs", type=int, default=30)
    benchmark.set_defaults(handler=cmd_benchmark)

    report = commands.add_parser("report", help="PNG/PDF visual reports for a run")
    report.add_argument("--run", required=True)
    report.set_defaults(handler=cmd_report)

    compare = commands.add_parser(
        "compare", help="candidate vs baseline -> PROMOTE or REJECT (advisory)"
    )
    compare.add_argument("--candidate", required=True, help="candidate run directory")
    compare.add_argument("--baseline", required=True, help="baseline run directory")
    compare.add_argument("--runs", type=int, default=30, help="benchmark iterations")
    compare.set_defaults(handler=cmd_compare)

    promote_parser = commands.add_parser(
        "promote", help="copy a validated export into the model zoo (manual approval)"
    )
    promote_parser.add_argument("--run", required=True)
    promote_parser.add_argument("--zoo", required=True, help="zoo root, e.g. models/")
    promote_parser.add_argument(
        "--approved-by",
        required=True,
        dest="approved_by",
        help="name of the human approving this promotion",
    )
    promote_parser.set_defaults(handler=cmd_promote)

    error_analysis = commands.add_parser(
        "error-analysis", help="top FP/FN images, worst confidence, worst localization"
    )
    error_analysis.add_argument("--run", required=True)
    error_analysis.add_argument("--split", default=None, help="default: the config's test split")
    error_analysis.add_argument("--top-k", type=int, default=10, dest="top_k")
    error_analysis.set_defaults(handler=cmd_error_analysis)

    qualitative = commands.add_parser(
        "qualitative", help="export random validation predictions as PNGs (GT + predicted boxes)"
    )
    qualitative.add_argument("--run", required=True)
    qualitative.add_argument("--split", default=None, help="default: the config's val split")
    qualitative.add_argument("--count", type=int, default=50)
    qualitative.add_argument("--seed", type=int, default=0)
    qualitative.set_defaults(handler=cmd_qualitative)

    coco_compare = commands.add_parser(
        "coco-compare", help="COCO-pretrained YOLOX-tiny vs this run -> PROMOTE or KEEP COCO"
    )
    coco_compare.add_argument("--run", required=True)
    coco_compare.add_argument("--split", default=None, help="default: the config's test split")
    coco_compare.add_argument("--zoo-root", required=True, dest="zoo_root")
    coco_compare.add_argument("--edge-project-root", required=True, dest="edge_project_root")
    coco_compare.add_argument("--runs", type=int, default=30, help="benchmark iterations")
    coco_compare.set_defaults(handler=cmd_coco_compare)

    candidate = commands.add_parser(
        "candidate", help="mark a run CANDIDATE — never installs into any model zoo"
    )
    candidate.add_argument("--run", required=True)
    candidate.add_argument("--notes", default="")
    candidate.set_defaults(handler=cmd_candidate)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except TrainingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
