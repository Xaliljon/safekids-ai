"""CLI end-to-end: the full mandated lifecycle through argument parsing.

import -> validate -> review -> publish -> statistics/report
+ import-pilot with lineage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acquisition_fixtures import build_evidence_export, build_urfall_raw

from guardian_ai.dataset import main


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("cli18")
    return {
        "root": root,
        "raw": build_urfall_raw(root / "raw"),
        "workspace": root / "ws",
        "registry": root / "registry",
    }


def out(capsys: pytest.CaptureFixture) -> dict:
    return json.loads(capsys.readouterr().out)


def test_01_import(case: dict, capsys: pytest.CaptureFixture) -> None:
    code = main(
        [
            "import",
            "urfall",
            "--raw",
            str(case["raw"]),
            "--workspace",
            str(case["workspace"]),
            "--consent",
            "research/urfall",
        ]
    )
    payload = out(capsys)
    assert code == 0
    assert payload["imported"] == 2
    assert payload["review_state"] == "imported"


def test_02_import_pilot(case: dict, capsys: pytest.CaptureFixture) -> None:
    export, record = build_evidence_export(case["root"] / "evidence")
    code = main(["import-pilot", "--evidence", str(export), "--workspace", str(case["workspace"])])
    payload = out(capsys)
    assert code == 0
    clip_id = payload["imported"][0]
    assert payload["lineage"][clip_id]["incident_id"] == record["incident_id"]
    assert "no automatic publication" in payload["note"]


def test_03_validate(case: dict, capsys: pytest.CaptureFixture) -> None:
    code = main(["validate", "--workspace", str(case["workspace"])])
    payload = out(capsys)
    assert code == 0
    assert payload["quality_ok"] and payload["privacy_ok"]
    assert (case["workspace"] / "metadata" / "quality-report.json").is_file()


def test_04_review_chain(case: dict, capsys: pytest.CaptureFixture) -> None:
    for state, actor in (
        ("annotated", "Annotator A"),
        ("reviewed", "Reviewer R"),
        ("approved", "Khalil"),
    ):
        code = main(
            [
                "review",
                "--workspace",
                str(case["workspace"]),
                "--to",
                state,
                "--by",
                actor,
                "--notes",
                f"cli {state}",
            ]
        )
        payload = out(capsys)
        assert code == 0
        assert payload["state"] == state
    assert payload["history"][-1]["by"] == "Khalil"


def test_05_review_refuses_skipping(case: dict, capsys: pytest.CaptureFixture) -> None:
    code = main(
        ["review", "--workspace", str(case["workspace"]), "--to", "annotated", "--by", "again"]
    )
    assert code == 1
    assert "illegal transition" in capsys.readouterr().err


def test_06_publish(case: dict, capsys: pytest.CaptureFixture) -> None:
    code = main(
        [
            "publish",
            "--workspace",
            str(case["workspace"]),
            "--registry",
            str(case["registry"]),
            "--name",
            "guardian-dataset",
            "--version",
            "1.0.0",
        ]
    )
    payload = out(capsys)
    assert code == 0
    assert payload["approved_by"] == "Khalil"
    assert Path(payload["training_ready"]).is_file()  # data.yaml for Sprint 19


def test_07_statistics_and_report(case: dict, capsys: pytest.CaptureFixture) -> None:
    assert main(["statistics", "--workspace", str(case["workspace"])]) == 0
    payload = out(capsys)
    assert payload["videos"] == 3  # 2 urfall + 1 pilot
    assert main(["report", "--workspace", str(case["workspace"])]) == 0
    payload = out(capsys)
    assert Path(payload["written"]).is_file()


def test_08_errors_exit_nonzero(case: dict, capsys: pytest.CaptureFixture) -> None:
    assert main(["validate", "--workspace", str(case["root"] / "nowhere")]) == 1
    assert "error:" in capsys.readouterr().err
    assert (
        main(
            [
                "import",
                "urfall",
                "--raw",
                str(case["root"] / "absent"),
                "--workspace",
                str(case["root"] / "ws2"),
            ]
        )
        == 1
    )
    assert "error:" in capsys.readouterr().err
