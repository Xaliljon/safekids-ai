# YOLOv12 Evaluation — Sprint 21

- **Date:** 2026-08-15
- **Outcome:** **E — integration blocked.** Stopped at the licence audit,
  before any code was written against YOLOv12.
- **Governed by:** ADR-0003 (detector selection and licensing), ADR-0009
  (model management), ADR-0020 (what the latency gate compares)

## Why YOLOv12 was evaluated

Guardian ships YOLOX-tiny (ADR-0003, Apache-2.0). YOLOv12 claims better
accuracy-per-latency than the YOLO line it descends from, and Guardian
Candidate v1's promotion has been blocked since Sprint 20 — so the question
"would a different detector simply be better" is a fair one to ask before
spending more effort on the current one.

Sprint 21 was asked to answer it with measurements, and to audit the licence
**before** integrating. The audit stopped the sprint.

## What was audited

| | Finding |
|---|---|
| Official implementation | `github.com/sunsmarterjie/yolov12` — the paper's own code (Tian, Ye & Doermann, arXiv:2502.12524, Feb 2025) |
| Repository licence | **AGPL-3.0** (`LICENSE`, verified by fetching it) |
| Package identity | its `pyproject.toml` declares `name = "ultralytics"`, `license = "AGPL-3.0"` |
| Upstream | `github.com/ultralytics/ultralytics` — **AGPL-3.0** |
| PyPI `ultralytics` | **AGPL-3.0** |
| PyPI `yolov12` | does not exist |
| Weights | published from the same repository under the same terms |
| Dependencies | `torch`, `torchvision`, `timm`, `albumentations`, `flash_attn`, `onnx`, `onnxruntime`, `onnxslim`, `pycocotools` — individually permissive; the blocker is the implementation itself, not its dependency tree |

## Why this is a harder blocker than YOLOv8 or YOLO11

ADR-0003 already blocks `yolov8` and `yolo11` as AGPL. YOLOv12 was worth
checking separately because a new model sometimes arrives with a new licence.
It did not — and it is worse than the two before it in one specific way.

The official YOLOv12 repository is **a fork of Ultralytics that installs as
the `ultralytics` package**. It is not a model with an AGPL dependency that
could be swapped for a permissive runtime: the model *is* the framework.
There is no "use the architecture, avoid the library" path, because the
architecture is only expressed inside the library.

## What Guardian's own gates do about it

The refusal is structural, not procedural — three independent gates, none of
which required changing for this sprint:

```
detector family        get_family("yolov12")  -> TrainingConfigurationError
                       "license-blocked (AGPL-3.0, ADR-0003) …"

export compatibility   ALLOWED_LICENSES = {Apache-2.0, MIT, BSD-2-Clause,
                       BSD-3-Clause, Proprietary-GuardianAI}
                       AGPL-3.0 is absent, so an exported AGPL model cannot
                       pass check_compatibility even if one existed

edge model zoo         LicensePolicy refuses an AGPL manifest at load time
                       (ADR-0009) — the box will not run it
```

Sprint 21's only code change was to register `yolov12` in the reserved table
**with its reason**. Before, it failed as a generic "unknown detector
family", which invites the next engineer to add it. Now the refusal states
the finding at the point where someone would try.

## What was NOT done, and why

Everything downstream of the audit. Per the sprint's own §3 — *"If YOLOv12
cannot legally be integrated under the current policy: STOP the integration
and report the blocker."*

No adapter was written, no checkpoint downloaded, no training run started,
no ONNX export attempted, no benchmark taken. Producing a benchmark for a
model that cannot ship would spend GPU budget to answer a question whose
answer changes nothing, and would leave AGPL code in the tree while doing
it.

The comparison table in the report is therefore Guardian v1's column with an
empty one beside it. That is the honest result of this sprint, not a
placeholder.

## What would unblock it

Three paths, in descending order of realism:

1. **Ultralytics Enterprise Licence.** A commercial licence exists and would
   make the AGPL obligation moot. This is a purchasing decision with a real
   price and it is the only path that is straightforwardly available today.
   It needs an ADR because it changes ADR-0003's premise.
2. **A permissively-licensed independent implementation.** None exists
   publicly for YOLOv12. Model *architectures* are not themselves
   copyrightable, so a clean-room implementation is legally plausible — but
   Sprint 19 already tried writing Guardian's own detector, and the audit
   found it could not converge objectness on a single overfit example while
   the official one converged cleanly. That is measured evidence, in this
   repository, that this path costs more than it looks like.
3. **Accepting AGPL.** Not a path. Guardian ships a commercial product to
   kindergartens; AGPL §13 would reach the deployed service. ADR-0003
   decided this and nothing in Sprint 21 disturbs it.

## Limitations of this audit

- Licence texts were read from the repositories' `main` branches on
  2026-08-15. A licence can change; a re-audit is cheap and should precede
  any future attempt.
- This is an engineering reading of published licence files, **not legal
  advice**. The conclusion that AGPL-3.0 is incompatible with Guardian's
  distribution model is ADR-0003's, already taken with that caveat.
- No claim is made about YOLOv12's technical merit. It was not measured.
  Whether it would beat YOLOX-tiny on Guardian's data is unknown and stays
  unknown until the licence question has an answer.
