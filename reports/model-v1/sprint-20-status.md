# Sprint 20 — First Production Training: Status

**This is a handoff note, not a completed research report.** Sprint 20's
real deliverable — Guardian Candidate Model v1 trained on the complete
19,940-image / 30-epoch spec on a Colab T4 GPU — has **not run yet**.
There is no GPU (T4 or otherwise) available in the environment this
sprint's platform work was done in, so the training run itself is the
one part of this sprint a human has to execute. Everything else the
spec asks for is prepped and locally verified.

## What shipped this sprint (platform changes, no architecture changes)

Sprint 19.1's comparison report disclosed one real gap and recommended
two follow-ups before a full-scale run: add warmup support, and try
`pretrained: true`. Both are now done:

1. **Warmup + cosine scheduler** (`guardian_ai/training/config.py`,
   `guardian_ai/training/engine.py`): `scheduler.warmup_epochs` linearly
   ramps the learning rate for N epochs before handing off to the
   existing cosine/step schedule (`SequentialLR(LinearLR, <main>)`).
   This is the fix for the SGD/lr=0.01 numerical divergence Sprint 19.1
   disclosed — see [Verification](#verification-the-warmup-fix-actually-works) below.
2. **`model-v1.yaml`** now sets `model.pretrained: true` (COCO transfer
   learning, auto-downloaded, checksum-pinned — Sprint 19.1's existing
   mechanism) and `scheduler.warmup_epochs: 5`, matching Sprint 20's
   spec exactly. Nothing else in the recipe changed.
3. **Checkpoint checksum + environment provenance**
   (`guardian_ai/training/experiment.py`, `.../detectors/yolox/family.py`):
   `experiment.json` now records the SHA-256 of whatever checkpoint was
   loaded (custom or auto-downloaded pretrained, keyed as `checksums.checkpoint`,
   distinct from the exported `model.onnx`'s checksum) and an `environment`
   block (Python/PyTorch/CUDA versions, GPU name if any) plus
   `duration_seconds` — the full "Experiment Tracking" list Sprint 20 asks
   for was already 90% there from Sprint 17; this closes the remaining gap.
4. **`guardian-validation.json`** (`guardian_ai/export/compat.py`,
   wired into `train export`): the existing `check_compatibility()` check
   now also writes its full result — input/output tensors, dynamic-shape
   flags, batch size, the manifest, license, sha256 — as a durable
   artifact next to `model.onnx`, not just a stdout print.
5. **`ai/training/notebooks/model-v1-training.ipynb`** updated to describe
   the Sprint 20 recipe (pretrained checkpoint, warmup) — the Run-All
   structure and CLI calls are otherwise unchanged from Sprint 19.

All of this is additive to the existing platform and detector-isolation
boundaries from Sprints 17–19.1 — no `DetectorFamily` protocol change, no
new detector-specific code outside `training/detectors/yolox/`.

## Verification: the warmup fix actually works

A bounded local dry run — 32 images (`dataset.max_samples: 32`), 8
epochs, CPU, otherwise the *exact* `model-v1.yaml` recipe (official
YOLOX-Tiny, COCO-pretrained, SGD lr=0.01, 5-epoch warmup + cosine, seed
42) — proves the config is Run-All-clean end to end and that warmup
actually prevents the divergence:

```
epoch 1/8 loss=97.5723
epoch 2/8 loss=41.1934
epoch 3/8 loss=11.6847
epoch 4/8 loss=10.4470
epoch 5/8 loss=11.6933   <- warmup ends here (5 epochs), no inf/nan
epoch 6/8 loss=10.5496
epoch 7/8 loss=10.8297
epoch 8/8 loss=8.8115
```

Smooth, finite, monotonically-trending-down loss — compare to Sprint
19.1's disclosed finding, where the *same* SGD/lr=0.01 hyperparameters
without warmup produced `inf`/`nan` poisoning within the first few
steps. This is the decisive confirmation the fix was correct, using the
same "run it and look directly at the numbers" methodology as every
other finding in this project.

The complete `train → evaluate → report → error-analysis → qualitative
→ export → benchmark → coco-compare → candidate` chain ran without a
single manual edit, and every new artifact came out as designed:

- `checksums.checkpoint` in `experiment.json`: the pinned COCO
  checkpoint's real SHA-256 (`9de513de...`), separate from `model.onnx`'s.
- `environment`: `{"python_version": "3.14.6", "torch_version": "2.12.1",
  "cuda_available": false, ...}` — correctly reports no GPU on this
  machine; the real run will show `cuda_available: true` and a T4 name.
- `duration_seconds`: populated (41.7s for this tiny run).
- `export/guardian-validation.json`: full contract (batch=1, static
  640×640 input, `output` float32, license `Apache-2.0`, manifest,
  8 passed clauses).
- `coco-compare` verdict: `REJECT` (candidate precision/recall both 0.0
  at this toy scale) — exactly the expected, honest outcome for 32
  images/8 epochs, the same pattern Sprint 19's report already
  documented at 256 images/6 epochs. This is not evidence about the real
  run's outcome either way.

Full artifacts from this dry run were kept out of version control (a
disposable scratch run, not a candidate) — the numbers above are quoted
directly from its `experiment.json`/log for the record.

## What has not happened

- The real training run: 19,940 train / 1,269 val / 3,692 test images,
  30 epochs, T4 GPU, `ai/training/notebooks/model-v1-training.ipynb`,
  Run All. This needs an actual Colab session with a T4 runtime.
- Guardian Candidate Model v1 (the real one) — error analysis on the
  full test set, 100 qualitative samples, the mandated COCO-pretrained
  comparison, and a PROMOTE/KEEP-COCO recommendation with real numbers.
- The Sprint 20 research report this file is standing in for.
- Any release, tag, or demo video — those describe a finished sprint,
  and this sprint isn't finished until the run above exists.

## Handoff: what to do with the real Colab run

1. Open `ai/training/notebooks/model-v1-training.ipynb` in Colab, set the
   runtime to a T4 GPU, upload the published `guardian-fall-detection-v1`
   registry export to Drive (see cell 1), Run All.
2. It writes everything into one `ai/training/runs/<experiment-id>/`
   directory and mirrors the key artifacts to Drive at the end (cell 21).
3. Hand back that run directory (or its Drive copy). From it the
   remaining Sprint 20 deliverables — the real research report,
   candidate/comparison verdict, and (if warranted) the sprint close-out
   — can be produced without re-running anything.
