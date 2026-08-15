# ADR-0020: What the Promotion Latency Gate Compares

- **Status:** Proposed
- **Date:** 2026-08-15
- **Deciders:** Founder, Lead Software Architect
- **Relates to:** ADR-0008 (inference runtime contracts), ADR-0009 (model
  management), ADR-0003 (detector selection); supersedes nothing — it fixes
  a clause ADR-0009 left underspecified
- **Blocks:** Guardian Candidate v1 promotion, and every promotion after it

## Context

Sprint 20 rejected Guardian Candidate v1 on the latency clause. Sprint 20.2
was asked to find out why, and the answer is that the clause did not measure
what it claims to.

`compare_models` benchmarks each artifact at **its own manifest input
shape**. The candidate declares 640×640; the COCO baseline declares
416×416. The gate then divides one by the other and compares the ratio to a
20 % slack:

| | input | mean | vs baseline |
|---|---:|---:|---:|
| COCO baseline | 416 | 18.45 ms | — |
| Candidate | 640 | 35.51 ms | 1.92× → **REJECT** |
| Candidate | **416** | **18.41 ms** | **1.00×** |

At matched input the candidate is exactly as fast as the baseline. The
entire rejection is 640² ÷ 416² = 2.37× the compute, by construction, and
nothing about the trained weights.

A ratio between two different workloads is not a slow model. It is not a
measurement at all — it is a unit error with a verdict attached.

Two further facts constrain the fix:

**Resolution is not available as a lever.** Retraining the gate's way out by
lowering the candidate to 416 was measured: precision collapses to 0.0000
(3015 false positives, 3692 false negatives). At 512 it is 0.0256. The model
needs 640 to detect anything, so "just match the baseline" is not a
promotion path — it is deleting the product.

**The benchmark does not run on the target.** Every number above comes from
development hardware (Apple M4 Max). `host_provenance()` already records
`is_edge_target: false` and `measurement_class: "development"`. The
charter's budget is detection under 500 ms **on an Edge box**, and no
measurement on a laptop can confirm or deny it.

## Decision

**1. A latency ratio between mismatched input shapes is not computed.**

Where the candidate and baseline declare different input shapes, the gate
does not divide the numbers and call the result a regression. It reports the
latency clause as `not_comparable`, states both shapes, and does not pass
it. Refusing to answer is honest; answering with an invalid ratio is not,
and it is the specific defect that rejected a healthy model.

This is not a policy choice — it is declining to publish a meaningless
number, and it stands whatever is decided below.

**2. The relative gate keeps its job, narrowed to what it can do.**

`candidate ≤ 1.20 × baseline` is a *regression* check and stays one: it is
meaningful only when both sides run the same workload on the same host. It
answers "did this generation get slower", which is worth knowing and is not
the product's question.

**3. The product's question needs an absolute budget on real hardware, and
until that exists the clause reports `unmeasured`.**

The charter asks whether the box holds its frame budget, not whether one
model beats another. That is an absolute number in milliseconds on Jetson
(primary) or Intel N100 (secondary), covering the whole pipeline — decode,
detect, track, event, risk — not the detector alone.

Until such a measurement exists, the gate reports the absolute clause as
`unmeasured` and **does not treat it as passed**. A budget clause that
silently passes because it ran on a laptop is worse than no clause: it
converts an unknown into a recorded success.

**4. A model may be promoted with the latency clause unresolved, and the
promotion record says so.** Blocking every promotion until Edge hardware
exists would freeze the project on a purchase order. Promotion is already
manual and human-approved (ADR-0009); the approver is told plainly that the
latency budget is unverified, and that admission travels with the model.

## Consequences

- **Candidate v1's rejection is void on the latency clause.** It is not
  thereby promotable: the scene-leakage finding means its accuracy numbers
  describe four rooms, and ADR-0005 §5 blocks promotion on Le2i pending the
  licence question. Three separate reasons, and only this one was a bug.
- **The gate becomes less decisive and more honest.** It will more often say
  "cannot tell" where it used to say REJECT. That is the correct direction
  for a gate whose false REJECT cost a sprint.
- **Someone must buy a Jetson.** This ADR converts a vague "measure on edge
  eventually" into a named blocker on a named clause. That is the intent.
- **Comparisons at matched resolution remain available** and are the right
  tool for "is this generation slower than the last one" — which is a
  question worth keeping, just not the one that was being asked.

## Alternatives Considered

- **Keep the ratio and widen the slack until 1.92× passes.** Rejected. It
  would make the clause pass by making it meaningless, and it is exactly
  what Sprint 20.2 was told not to do — the gate would then approve a
  genuinely 2× slower model just as readily.
- **Force both models to a common resolution before benchmarking.** Correct
  for a regression check and adopted for that (§2), but wrong as the only
  answer: exporting the COCO baseline at 640 was refused by the export
  platform's own numerical parity guard (`max |Δ| = 3.33e-03 > 1e-04`). That
  guard was left alone. A gate that requires re-exporting the baseline for
  every candidate is also a gate that will be skipped.
- **Drop the latency clause entirely until Edge hardware exists.** Rejected.
  Silence and `unmeasured` look identical in a report six months later, and
  the clause's absence would be read as its absence of concern.
- **Treat development-hardware latency as a proxy with a fudge factor.**
  Rejected. The ratio between an M4 Max and a Jetson Orin Nano is not a
  constant across operators — it varies with memory bandwidth, provider and
  quantisation — so the factor would be invented, and an invented number in
  a safety budget is worse than a missing one.

## Open Questions

1. Which Edge target defines the budget when Jetson and N100 disagree — the
   primary alone, or the weaker of the two?
2. Is the 500 ms detection budget per-camera or shared across all cameras on
   one box? The charter does not say, and a four-camera box makes the
   difference decisive.
3. Should the absolute clause measure the full pipeline or the detector
   alone? Sprint 20.2 §3 left the component breakdown unmeasured; the answer
   changes what hardware is sufficient.
