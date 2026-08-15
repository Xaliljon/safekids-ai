# Guardian Candidate v1 — provenance review

**The checkpoint is the right one. The metrics it earned mean less than they look like.**

Sprint 20.2 flagged that the checkpoint handed back (`last.pt`) sits at
epoch 13 of a 30-epoch configuration, and asked whether it is the model
that produced the Sprint 20 report. Answering that opened two more
questions that matter more than the original one.

## 1. The checkpoint is correct — the run early-stopped

`metrics.json` settles it:

```json
{"metric": "f1", "best_f1": 1.0, "epochs_completed": 14,
 "epochs_planned": 30, "stopped_early": true}
```

Fourteen epochs ran (0–13); `last.pt` is the final one. `experiment.json`'s
`status: completed` is honest — the run completed by early stopping, not by
exhausting its 30 epochs. **The epoch-13 concern is closed.**

Worth noting for anyone reading the wall clock: `duration_seconds` is
3,088,499 (≈36 days) because the run spans a Colab disconnect. The log shows
it training on 2026-07-09, then resuming on 2026-08-14 at epoch 12. That is
calendar time, not GPU time; the per-epoch stamps show ~11.5 minutes each.

## 2. Early stopping fired on a saturated metric, not on a plateau

```
epoch 10/30 loss=2.0814 val_f1=1.0000
epoch 11/30 loss=2.0188 val_f1=0.9819
epoch 12/30 loss=1.9580 val_f1=1.0000
epoch 13/30 loss=1.9218 val_f1=1.0000
epoch 14/30 loss=1.8787 val_f1=0.9917
early stopping: no f1 improvement for 10 epoch(s)
```

F1 first reached **1.0 at epoch 3** and can go no higher, so "no
improvement" was true from that point on by arithmetic rather than by the
model having stopped learning. Training loss was still falling monotonically
when the run was cut: 15.29 → 1.88, still decreasing on the final epoch.

**A metric that saturates cannot drive early stopping.** The patience
counter measured the ceiling, not the model. Whether more epochs would have
helped is unknown and unknowable from this run — which is the point.

## 3. The validation set cannot tell this model apart from its training set

This is the finding that matters. `val_f1 = 1.0` by epoch 3 is not a good
model; it is an easy validation set.

Splitting is **by clip**, not by frame — `training_export.py` writes every
frame of a clip into one split, so there is no frame-level leak. That was
checked first and it is clean.

The leak is one level up. Scene composition of the three splits:

| Split | Images | Scenes |
|---|---|---|
| train | 19940 | coffee-room-01, coffee-room-02, home-01, home-02 |
| val | 1269 | coffee-room-01, coffee-room-02, home-01, home-02 |
| test | 3692 | coffee-room-01, coffee-room-02, home-02 |

**Every scene in validation is also in training.** The model trains on clips
filmed in `home-01` and is validated on different clips filmed in the same
room, from the same fixed camera, under the same lighting — and three of the
four scenes recur in test as well.

So `precision 0.9902` measures *same-room recognition*, not generalization.
The model has learned "a person in these four rooms" and is scored on
exactly those rooms.

## What this does and does not invalidate

It does **not** mean the training platform is broken or the run was wasted.
The pipeline works end to end, the loss curve is healthy, the export is
valid, and the model genuinely detects people in Le2i footage.

It does mean:

- **The headline metrics are not evidence of kindergarten performance.**
  They were never going to be — Le2i is adults in French homes and offices —
  but scene leakage means they are not even evidence of *Le2i*
  generalization. They describe four specific rooms.
- **The false-positive rate the charter asks about remains unmeasured.**
  This was already true from the domain gap; scene leakage means the
  existing number cannot be used as an optimistic bound either.
- Today's live run is the corroboration: the same model, on real CCTV and
  kindergarten footage, produced behaviour this test set gave no warning
  about — `aspect_ratio_flip` pinned at 1.00 on 60 consecutive candidates.

## What would fix it

1. **Split by scene, not by clip.** Hold out `home-02` (or any whole scene)
   entirely for test. The number that comes back will be lower and it will
   mean something.
2. **Stop early on loss, or on a metric with headroom.** F1 at this
   difficulty saturates; `mAP@50-95` does not.
3. **Get kindergarten footage into the dataset.** Neither fix above changes
   the fact that the product's domain is not in the training data at all.

None of these are code defects — they are dataset and configuration
decisions, and they belong to the same architecture review Sprint 20.2 is
already waiting on.

### Update: fix 1 is built

Splitting is now by **split group** rather than by clip id. An importer
declares what must not straddle splits — the scene for Le2i, the subject
for GMDCSA24, the whole corpus for UR Fall (one laboratory, one camera, and
no subject identifiers in the public labels). `straddling_groups()` reports
any group appearing in more than one split, and one test per shipped
importer asserts a group is declared at all.

This does not retroactively fix `guardian-fall-detection-v1@1.0.0` — that
version was published under the old assignment and versions are immutable.
The number it produced still describes four rooms. What changed is that the
*next* import cannot repeat it, which is the precondition for fixes 2 and 3
meaning anything.

Fix 2 (a metric with headroom) and fix 3 (kindergarten footage) are
untouched and still belong to the architecture review.

## Sprint 20.2 addendum: the like-for-like latency comparison

The architecture review needs to know whether the candidate is genuinely
slower than the baseline or merely larger-input. Measured at matched
resolution on the same host (Apple M4 Max, development hardware):

| | mean | ratio |
|---|---:|---:|
| COCO baseline @416 | 18.45 ms | — |
| Candidate @416 | 18.41 ms | **1.00×** |
| Candidate @640 | 35.51 ms | 1.92× |

**At the same input size the candidate is exactly as fast as the baseline.**
The entire latency rejection is the 640 vs 416 input difference — 2.37× the
compute by construction — and nothing about the trained weights.

Exporting the COCO baseline at 640 for the symmetric check was refused by
the export platform's own parity guard (`max |Δ| = 3.33e-03 > 1e-04`). That
guard was left alone; the 416 comparison answers the same question.
