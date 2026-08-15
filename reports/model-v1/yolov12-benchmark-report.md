# YOLOv12 Benchmark Report — Sprint 21

**Result: E — integration blocked. No benchmark was produced, and that is
the finding rather than a gap in it.**

## 1. Executive summary

Sprint 21 asked whether YOLOv12 is objectively better than Guardian v1 under
identical dataset, evaluation, export and latency conditions. The sprint's
own §3 required a licence audit before integration, with an instruction to
stop if the licence violates Guardian's policy.

It does. The audit stopped the sprint before any YOLOv12 code entered the
repository.

The official YOLOv12 implementation is published under **AGPL-3.0**, and not
as a dependency that could be replaced: `sunsmarterjie/yolov12` is a fork of
Ultralytics whose `pyproject.toml` declares `name = "ultralytics"` and
`license = "AGPL-3.0"`. The model is the framework. ADR-0003 blocked
`yolov8` and `yolo11` for exactly this licence; YOLOv12 is the same blocker
with one fewer escape route.

The question "is YOLOv12 better" is therefore **unanswered and deliberately
so**. Measuring a model that cannot ship would spend GPU budget on a number
that changes no decision, and would leave AGPL code in the tree while doing
it.

## 2. YOLOv12 source

| Field | Value |
|---|---|
| Implementation | `github.com/sunsmarterjie/yolov12` (the paper's official code) |
| Paper | Tian, Ye & Doermann, *YOLOv12: Attention-Centric Real-Time Object Detectors*, arXiv:2502.12524 (2025-02-19) |
| Branch audited | `main`, fetched 2026-08-15 |
| Package name on install | `ultralytics` |
| Upstream | `github.com/ultralytics/ultralytics` |
| PyPI `yolov12` | does not exist (404) |
| Commit pinned | **none** — pinning a commit is an integration step and integration was stopped |
| Checkpoint SHA-256 | **not recorded** — no checkpoint was downloaded |

## 3. Licence analysis

| Artifact | Licence | How verified |
|---|---|---|
| `sunsmarterjie/yolov12` repository | AGPL-3.0 | fetched `LICENSE` |
| its `pyproject.toml` | `license = { "text" = "AGPL-3.0" }` | fetched |
| `ultralytics/ultralytics` | AGPL-3.0 | fetched `LICENSE` |
| `ultralytics` on PyPI | AGPL-3.0 | package metadata |
| Pretrained weights | published from the same repository, same terms | repository |
| Dependencies (`torch`, `torchvision`, `timm`, `albumentations`, `flash_attn`, `onnx`, `onnxruntime`, `onnxslim`, `pycocotools`) | individually permissive | not the blocker |

**Verdict: incompatible with Guardian's licensing policy (ADR-0003).**

Guardian ships a commercial product to kindergartens. AGPL §13 reaches a
deployed service. ADR-0003 decided this for the YOLO line and Sprint 21
found nothing that distinguishes YOLOv12 from it — except that the usual
mitigation (keep the model, replace the framework) is unavailable here,
because the implementation *is* Ultralytics under a different repository
name.

## 4. Architecture integration

**None performed.** No adapter, no family registration, no configuration
key, no engine change.

One change was made, and it is the audit's own output rather than an
integration: `yolov12` now appears in the reserved-families table with its
reason. Previously it failed as a generic *unknown detector family*, which
tells the next engineer nothing and invites them to add it. It now fails
with the finding, at the point where someone would try:

```
detector family 'yolov12' is reserved, not yet trainable: license-blocked
(AGPL-3.0, ADR-0003) — the official implementation (sunsmarterjie/yolov12)
is a fork of Ultralytics that installs as the 'ultralytics' package; the
model is the framework, so there is no weights-only path. See
architecture/yolov12-evaluation.md (Sprint 21)
```

Two further gates would have refused it downstream, and neither needed
changing: `ALLOWED_LICENSES` for on-device export excludes AGPL-3.0, and the
edge `LicensePolicy` refuses an AGPL manifest at model load (ADR-0009).

## 5. Training configuration

**Not applicable.** No training run was started.

## 6. Dataset

`guardian-fall-detection-v1@1.0.0` was **not modified, not re-split, and not
read** by this sprint.

## 7. Training result

**None.**

## 8. Accuracy metrics

**Not measured.** See §14 for what Guardian v1's column looks like beside an
empty one.

## 9. Error analysis

**Not produced.** Error analysis requires predictions; there are none.

## 10. PyTorch benchmark

**Not run.**

## 11. ONNX benchmark

**Not run.** No export was attempted, so no parity check exists to pass or
fail.

## 12. Edge / development benchmark

**Not run.** Guardian v1's existing figures remain **development hardware**
(Apple M4 Max, `is_edge_target: false`) and are not production Edge numbers
— unchanged from Sprint 20.2 and restated here so the comparison table below
is not misread.

## 13. Memory

**Not measured.**

## 14. Guardian v1 comparison

Guardian v1's column comes from the existing Sprint 20.2 measurements and
was **not re-run** for this sprint (§9 of the brief). YOLOv12's column is
empty because the sprint stopped at §3.

| Metric | Guardian v1 (candidate @640) | YOLOv12 |
|---|---:|---|
| Precision | 0.9902 | not measured |
| Recall | 0.9832 | not measured |
| F1 | 0.9867 | not measured |
| mAP@50 | 0.2442 | not measured |
| mAP@50-95 | 0.1399 | not measured |
| False positives | 36 | not measured |
| False negatives | 62 | not measured |
| Model size | 19.463 MB | not measured |
| Mean latency | 35.51 ms | not measured |
| P95 latency | 39.82 ms | not measured |
| Memory | 73.58 MB (Colab CPU EP) | not measured |

Two cautions about the left column, both already on record and neither
introduced here:

- Its precision/recall describe **four rooms**, not generalization: every
  validation scene is also a training scene (candidate provenance review).
  The scene-leakage defect is fixed for future imports; this published
  version predates the fix and is immutable.
- Its latency was measured on development hardware. The Sprint 20.2
  allowance of **111.462 ms mean** is a Colab-CPU figure, and the 35.51 ms
  above is Apple M4 Max. Neither is a Jetson.

## 15. Promotion gate result

**Not run.** The gate compares two evaluated models; there is only one.

Guardian v1's own standing result is unchanged by this sprint: REJECT on
latency in Sprint 20, which ADR-0020 has since shown to be an artifact of
comparing a 640 candidate against a 416 baseline. That correction belongs to
ADR-0020 and is not a Sprint 21 finding.

**YOLOv12 is ineligible for promotion** — not on measured merit, but because
it cannot be exported, loaded or shipped under ADR-0003.

## 16. Limitations

- Licence texts were read from `main` on 2026-08-15. Licences change; a
  re-audit should precede any future attempt and costs minutes.
- This is an engineering reading of published licence files, **not legal
  advice**.
- **No claim is made about YOLOv12's technical merit.** It may well be
  better than YOLOX-tiny. Sprint 21 does not know, and nothing in this
  report should be cited as evidence either way.
- The audit covered the official implementation and its upstream. A
  permissively-licensed third-party implementation could exist and was not
  found; absence of evidence here is weak evidence of absence.

## 17. Recommendation

**Do not integrate YOLOv12 under the current policy.** Close Sprint 21 at
the blocker.

If the accuracy question is worth pursuing, the decision is commercial
before it is technical, and it should be taken in that order:

1. **Price the Ultralytics Enterprise Licence.** It is the only path
   available today. It changes ADR-0003's premise and therefore needs an
   ADR, not a sprint.
2. **Only then benchmark.** Buying a licence to evaluate a model is a
   defensible experiment; integrating first and resolving the licence later
   is not, and would put AGPL code in a repository whose whole detector
   policy exists to keep it out.
3. **Consider RT-DETR instead.** It is already reserved in the family table
   as Apache-2.0 and scheduled after YOLOX. It answers the same underlying
   question — "is there a better detector than YOLOX-tiny" — with no licence
   purchase and no blocker.

The third option is the one this report would act on first. It costs a
sprint rather than a contract, and the question Sprint 21 set out to answer
was about detector quality, not about YOLOv12 specifically.

## Decision matrix

| Criterion | Guardian v1 | YOLOv12 | Winner |
|---|---:|---|---|
| Precision | 0.9902 | not measured | — |
| Recall | 0.9832 | not measured | — |
| F1 | 0.9867 | not measured | — |
| mAP@50 | 0.2442 | not measured | — |
| mAP@50-95 | 0.1399 | not measured | — |
| FP | 36 | not measured | — |
| FN | 62 | not measured | — |
| Mean latency | 35.51 ms | not measured | — |
| P95 latency | 39.82 ms | not measured | — |
| Model size | 19.463 MB | not measured | — |
| Memory | 73.58 MB | not measured | — |
| **Licence** | **Apache-2.0** | **AGPL-3.0** | **Guardian v1** |

**Classification: E — YOLOv12 integration blocked.**

Every technical row is undetermined and will stay so. The one row that was
decided is the one the sprint was told to check first.

## Reproducing this audit

```bash
curl -sSL https://raw.githubusercontent.com/sunsmarterjie/yolov12/main/LICENSE | head -3
curl -sSL https://raw.githubusercontent.com/sunsmarterjie/yolov12/main/pyproject.toml | grep -E '^name|license'
curl -sSL https://raw.githubusercontent.com/ultralytics/ultralytics/main/LICENSE | head -3
```

```bash
python -c "from guardian_ai.training.families import get_family; get_family('yolov12')"
```
