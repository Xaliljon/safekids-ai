# ADR-0005: Dataset Governance

- **Status:** Proposed
- **Date:** 2026-08-15
- **Deciders:** Founder, Lead Software Architect, and — before any pilot collection — legal counsel
- **Relates to:** ADR-0010 (dataset platform), ADR-0017 (evidence), ADR-0003/0009 (licence gates), docs/04 (AI ethics)

## Context

The index has carried this entry as "**needed before first data collection**"
since ADR-0001. Collection has not started, so nothing has been violated —
but the platform that would do it is complete, and the model that would use
it is trained and waiting on data. This is the last thing standing between
Guardian and the only dataset that can answer its central question.

That question is unanswered today. Guardian Candidate v1 scores 0.9902
precision on Le2i — adults falling in French homes and offices — and a
provenance review showed the score also carries scene leakage: every
validation scene appears in training. The charter's success metric is a low
false-positive rate *in a kindergarten*, and the current data cannot speak
to it even optimistically.

A survey of public sources settles where that data can come from. There is
no kindergarten fall dataset. Every public fall corpus is elderly or general
adult; the largest aggregate, OmniFall, is CC BY-NC-SA — non-commercial,
which Guardian is not — and its components already include the Le2i data in
hand. Classroom datasets exist but cover school-age behaviour recognition,
not preschool falls. Nobody publishes footage of small children, and the
reasons they do not are the same reasons Guardian must be careful.

So the only realistic source is a pilot kindergarten's own cameras, and the
material is video of identifiable young children. ADR-0010 built the
mechanism for it — a privacy gate that demands a consent reference, an
ethics-review reference for minors, forbidden identity keys, human-only
annotation, full incident-to-model lineage. What the mechanism references
and does not define is the governance. That is this ADR.

## Scope: what this ADR does and does not block

It governs **material depicting minors**. That is where consent, ethics
review and withdrawal apply, and it is why the index has carried this entry
as a prerequisite since ADR-0001.

It does **not** gate published adult research corpora under
commercial-permissive licences. Those continue to flow through ADR-0010's
existing quality, privacy and licence gates, and adding them needs nothing
from this document. Stating that explicitly matters: Guardian already ships
tested importers for UR Fall and GMDCSA24 that the published
`guardian-fall-detection-v1@1.0.0` does not use — it contains four Le2i
scenes and nothing else, which is the direct cause of the scene leakage
found in the candidate provenance review. Ingesting them is unblocked work,
and a governance document that accidentally froze it would be doing harm
rather than preventing it.

The two tracks are independent: adult corpora make the *existing* number
mean something; only the pilot can answer the charter's question about
kindergartens.

## Decision

1. **Guardian collects only from sites it has a written data agreement
   with.** No scraping, no purchased footage of children, no third-party
   corpus containing minors. The `import-pilot` path is the only route by
   which children's material enters the platform, and it starts from a
   decrypted evidence export the site itself produced.

2. **Consent is specific, per-child, and revocable in writing.** A
   kindergarten's own operating consent is not consent for this. The
   agreement must name, in the guardians' language: that short clips of
   *safety events involving their child* may be retained and annotated to
   improve detection; that no faces are identified and no child is named;
   that footage never leaves the agreed processors; and how to withdraw.
   The privacy gate's `consent_reference` points at that executed
   agreement, not at a checkbox.

3. **The ethics-review reference is an artifact, not a field.** For any
   dataset containing minors it must resolve to a written review that
   records: who reviewed, what they saw, the lawful basis relied on, the
   retention period, and the withdrawal procedure. A dataset whose
   reference resolves to nothing is not publishable — the gate should
   verify resolution, not merely presence.

4. **Withdrawal outranks reproducibility.** This is the decision this ADR
   exists to make. ADR-0010 makes published versions immutable so a
   training run can be reproduced exactly; a guardian withdrawing consent
   requires their child's material to go. These conflict, and consent wins:

   - Withdrawal marks the affected clips and publishes a **new dataset
     version** without them.
   - The prior version is **tombstoned as WITHDRAWN**: its manifest
     survives for audit, and the registry **refuses to load it for
     training**. Immutability is preserved as a historical fact and
     revoked as a licence to use.
   - Any experiment whose `experiment.json` names a withdrawn version is
     **flagged, not deleted**. Weights are derived from material, not the
     material itself, and destroying a trained model is not obviously owed;
     but such a model may not be promoted, and the flag is what stops it
     quietly shipping.

   Reproducibility is a property Guardian values highly. It is not worth
   more than a parent's ability to change their mind about their child.

5. **Third-party datasets must permit commercial use, and the registry
   enforces it.** The model zoo already refuses AGPL structurally
   (ADR-0003/0009); the dataset registry gains the symmetric gate and
   refuses non-commercial licences (CC BY-NC*, research-only, and academic
   terms that forbid production use). A licence field that cannot be
   mapped to a known permissive licence blocks publication. This is why
   OmniFall cannot be used despite fitting the problem well.

6. **What is never collected, at any consent level:** audio (blocked on a
   PRD that does not exist), face embeddings or any identity feature,
   named individuals, footage from outside the declared safety events, and
   material from any site without an agreement. These are not defaults to
   be tuned per deployment; they are the product's boundary and moving one
   is an ADR of its own.

7. **Dataset retention is bounded and separate from evidence retention.**
   Evidence on a box expires by age and by storage budget (ADR-0017,
   ADR-0019). Dataset material is a different artifact with a different
   clock: it lives for the retention period named in the ethics review,
   after which it is deleted and the version tombstoned as EXPIRED. A
   dataset with no stated retention period is not publishable.

## Consequences

- **Collection cannot start on engineering's schedule.** An executed
  agreement and a written ethics review are prerequisites, and both involve
  people outside this repository. That is the intended cost.
- **The withdrawal path has real engineering weight**: a version diff, a
  tombstone status the registry honours on load, an experiment-level flag,
  and a promotion block. None of it exists yet; all of it is cheap compared
  to discovering it is missing when a parent asks.
- **Some public data becomes unusable that would have been convenient.**
  OmniFall is the concrete example. The licence gate will say so at publish
  time rather than after a model is trained on it.
- **Le2i stays legitimate** — adults, published for research under its own
  terms — but this ADR makes explicit that it can never answer the
  kindergarten question, only keep the pipeline honest until real data
  exists.
- Auditability improves in a way that matters commercially: a kindergarten
  director asking "what happens to footage of my children" can be answered
  from documents, not assurances.

## Alternatives Considered

- **Synthetic children's data instead of real footage:** attractive and
  rejected as the primary path — a model validated only on generated
  children would carry an unmeasurable domain gap into exactly the
  population it protects. Useful as augmentation once real data exists and
  the gap can be measured.
- **Anonymise (blur faces) and treat the result as non-personal:** rejected
  — blurred video of a specific child in a specific room on a specific day
  remains identifiable in context, and treating it otherwise would be a
  legal position this project is not entitled to take on its own.
- **Keep immutability absolute and refuse withdrawal:** rejected outright.
  It is the wrong answer for a child-safety product and would likely be the
  wrong answer legally; the fact that it is the convenient engineering
  answer is precisely why it needed to be written down as rejected.
- **Delete models trained on withdrawn data:** considered and not adopted
  as an automatic rule. Weights are a derivative, the obligation is
  unsettled, and an automatic rule here would be a legal claim rather than
  an engineering one. Flag and block promotion; escalate to counsel.
- **Buy a commercial childcare dataset:** rejected — consent obtained by a
  vendor from other people's children, for purposes those guardians never
  saw, is not consent Guardian can stand behind in front of a director.

## Open Questions — legal, not engineering

These block *collection*, not this ADR's acceptance. Each needs counsel in
the operating jurisdiction:

1. What is the lawful basis for processing minors' video for model
   improvement, and does legitimate interest ever apply or is explicit
   guardian consent always required?
2. What is the maximum defensible retention period for annotated clips of
   identified minors?
3. On withdrawal, is there an obligation extending to models already
   trained on the material — and does that change if the model is deployed?
4. Does a kindergarten act as controller, processor, or joint controller
   with Guardian, and which of them owes the withdrawal mechanism?
