# ADR-0019: Evidence Storage Bounds

- **Status:** Proposed
- **Date:** 2026-08-15
- **Deciders:** Founder, Lead Software Architect
- **Extends:** ADR-0017 (evidence management)

## Context

ADR-0017 promised that "everything expires; nothing is kept forever", and
delivered it with an age-based retention policy: dismissed evidence lives
24 hours, confirmed 30 days, critical 90 days, pending 30 days. Every clip
does eventually expire.

The disk fills first.

Running the real pipeline against a looping test clip produced an incident
roughly every ten seconds. In a few hours that is 2602 evidence records and
**152 GB** — measured, on a development machine, with the retention sweeper
running the whole time. It swept nothing, correctly: not one record was
older than 24 hours.

A box that produces incidents faster than its shortest retention window
expires them has no upper bound on evidence at all. `deploy/install.sh`
refuses to install below 5 GB free, and this fills that in under an hour of
a busy day. The failure is not theoretical and it is not slow.

Age answers *when may this be deleted*. Nothing currently answers *how much
may exist at once*.

## Decision

1. **Evidence gets a storage budget, enforced after age.** The sweeper
   keeps its existing age pass unchanged, then — while the evidence
   directory exceeds `max_total_bytes`, or the filesystem has less than
   `min_free_bytes` free — evicts further records until both hold. Age
   expiry stays the primary mechanism; the budget is the backstop that
   makes "nothing is kept forever" true of the disk and not only of each
   individual clip.

2. **Eviction order follows review state, not age alone.** This is the part
   that matters. Evidence for an incident nobody has looked at is the
   evidence most likely to be needed, so it goes last:

   | Order | Class | Why it goes first |
   |---|---|---|
   | 1 | Dismissed | a human already judged it not an incident |
   | 2 | Confirmed | judged, and the decision is recorded independently of the clip |
   | 3 | Pending review | **nobody has seen this yet** |

   Within each class, oldest first, and CRITICAL severity last. A dismissed
   critical still outranks a pending low.

3. **Evicting unreviewed evidence is a reportable event, never a silent
   one.** If the budget can only be met by deleting PENDING_REVIEW
   evidence, the box has more incidents than it can hold and a director is
   about to lose something they never saw. That eviction is logged at
   warning level with the incident id, counted, and surfaced through
   `/health` as a degraded evidence subsystem. Quietly deleting the
   unreviewed record of a possible injury is the one behaviour this ADR
   exists to prevent.

4. **The metadata tombstone survives the clip.** ADR-0017 §? already
   deletes clip bytes while keeping a metadata record; budget eviction uses
   the same path with `EvidenceStatus.EXPIRED`. What a director loses is
   the footage, never the fact that an incident existed and what was
   decided about it. The incident, its signals, and its review outcome live
   in the risk engine and the notification record, not in the clip.

5. **Defaults are a starting point, not a finding.** `max_total_bytes`
   defaults to 20 GB and `min_free_bytes` to 10 GB — twice the installer's
   own floor, so the budget bites before the box endangers the rest of the
   system. Both are per-deployment configuration in the same object as the
   age windows. The right numbers depend on the box's disk and on how many
   incidents a real kindergarten produces in a day, and neither is known
   yet: the only measurement available is a synthetic clip on loop, which
   is an upper bound on incident rate, not an estimate of one.

## Consequences

- **A busy box now loses footage rather than filling its disk**, and it
  loses the least-needed footage first. That is the correct trade — a box
  that stops working protects nothing — but it is a real loss and the
  eviction counter in `/health` is how an operator sees it happening.
- **A box hitting the budget is a box that is misconfigured or under-tuned.**
  Sustained pending-review eviction means the detector's thresholds are
  producing more incidents than anyone can review; the fix is upstream in
  the risk policy, not in more disk. The health signal is deliberately
  degraded rather than informational so that this surfaces.
- The sweeper now stats the evidence directory each pass. At the observed
  record count (thousands) this is milliseconds every ten minutes, and it
  reads sizes from the store's own metadata rather than walking the tree.
- **This does not bound the ring buffers.** Frames held in memory before an
  incident opens are bounded by their own configuration (ADR-0017); this
  ADR is about what reaches disk.
- Age retention is untouched, so a quiet box behaves exactly as ADR-0017
  described. Only a box past its budget behaves differently.

## Alternatives Considered

- **Shorten the age windows instead:** rejected — it solves the disk by
  discarding evidence a director may still be entitled to, on every box,
  including quiet ones that were never near the limit. The windows encode
  what evidence is *for*; the budget encodes what the hardware can hold.
  They are different questions and collapsing them loses the first.
- **Evict strictly oldest-first, ignoring review state:** simpler, and
  rejected — on a busy box the oldest records are precisely the ones
  waiting longest for review. It would delete exactly the evidence most
  likely to be needed.
- **Refuse to record new evidence when full** (fail closed): rejected —
  the newest incident is the one most likely to still be actionable, and a
  box that stops recording is a box whose evidence platform has silently
  turned off. Evicting the least-needed old record is the better loss.
- **Free-disk floor only, no total ceiling:** rejected as the sole
  mechanism — it lets evidence expand to fill whatever else is free and
  turns every other subsystem's disk use into an evidence problem. Both
  bounds are cheap; keeping both means evidence has a budget *and* cannot
  starve the box.
- **Delete the metadata too:** rejected — ADR-0017's tombstone is what lets
  a director see that a clip existed and was expired rather than that
  nothing ever happened.

## Open Questions

1. What is the real incident rate in a kindergarten? Every number here is
   derived from a synthetic clip on loop. The pilot answers this, and the
   defaults should be revisited with its data.
2. Should the budget scale with the disk (e.g. 25% of capacity) rather than
   being absolute? Absolute is simpler to reason about on a fixed-spec Edge
   Box; a percentage travels better across hardware revisions.
