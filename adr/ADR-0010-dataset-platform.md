# ADR-0010: Dataset Platform

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

SafeKids models will be trained on data that includes children — the most
sensitive data this company will ever hold. docs/04 sets the ethics bar
(lawful collection, documented consent, bias evaluation, privacy
protection); Sprint 7 turns that bar into infrastructure in `ai/`, before
any data is collected, so the first real dataset cannot be assembled the
wrong way.

## Decision

1. **Annotation format: JSON Lines, normalized geometry.** One JSON object
   per sample; boxes in normalized [0, 1] coordinates, top-left origin —
   the same convention as edge detections (ADR-0006), so datasets, model
   outputs, and evaluation all speak one geometry. JSONL is diffable,
   streamable, mergeable in PRs, and needs no library. Sample identity is
   the relative media path; media live in DVC storage, never in git and
   never in the registry (metadata only).

2. **Versioned taxonomy, bound per dataset.** A dataset binds to a named,
   versioned `LabelTaxonomy`; unknown labels fail quality validation. The
   V1 vocabulary is scene-state labels only (`person`, `child`, `adult`) —
   taxonomies never contain identity labels (docs/04: no facial
   recognition, no profiling).

3. **Ethics fields are required manifest fields.** `dataset.json` must
   declare provenance (`collected_by`, `consent_reference`), an explicit
   privacy posture (`contains_minors`, `anonymized`), and — whenever minors
   appear — an ethics `review_reference`. A dataset that cannot answer
   these questions cannot be represented, let alone published.

4. **Deterministic, hash-based splits.** A sample's train/val/test
   assignment is a pure function of its path (SHA-256 → fraction →
   cumulative ratio). No seeds, no order dependence — and adding samples
   never moves existing ones between splits, which is how eval data
   quietly leaks into training across dataset versions.

5. **Two publish gates: quality and privacy.** Publication runs structural
   quality validation (duplicates, cross-split leakage, unknown labels,
   empty splits — ERRORs block; WARNINGs surface) and the privacy checker
   (consent present, minors reviewed, identity-bearing attribute keys,
   email/phone patterns in values, absolute/escaping paths — any violation
   blocks). The checker is a mechanical floor, not a substitute for human
   ethics review.

6. **Registry mirrors the model zoo** (ADR-0009): immutable versions under
   `<root>/<name>/<version>/`, staged atomic publishes, `.staging` swept on
   startup, checksums computed at publish and re-verified on `get()`,
   latest-by-semver resolution. One mental model for both artifact stores.

7. **Metrics are the start of bias evaluation.** Every dataset yields
   label balance, split composition, background share, and imbalance
   ratio — the mechanical inputs to the bias review docs/04 requires.

## Consequences

- The first real data collection inherits consent, review, split, and
  privacy discipline on day one, instead of retrofitting it onto an
  existing pile of video.
- ai/ duplicates small pieces of edge (semver parsing, normalized bbox)
  because cross-app imports are forbidden (ADR-0001). Flagged follow-up:
  promote `SemanticVersion` and the bbox convention into `guardian_common`
  as a deliberate PR.
- The privacy checker will produce false negatives (it cannot see pixels);
  anonymization and consent verification remain human responsibilities,
  which is why the manifest points at review documents rather than
  claiming compliance itself.
- Hash-based splits cannot do stratified or grouped splitting (e.g. all
  frames from one camera session together). Grouped splitting is a real
  future need (session leakage) — it will extend the split key, not
  replace determinism.

## Alternatives Considered

- **COCO JSON (single file):** rejected — one giant JSON is undiffable and
  unmergeable in review; per-line records fit the docs-and-PR workflow.
  Converters can be written when interop demands them.
- **Random seeded splits:** rejected — seeds get lost, order dependence
  creeps in, and regenerated splits silently reshuffle samples across
  versions.
- **DVC pipelines as the registry:** rejected as the *registry* — DVC
  stays the media transport/storage layer; gating, ethics fields, and
  verification logic belong to code we own and test.
- **Optional ethics fields with linter warnings:** rejected — optional
  means absent; the entire point is that unanswered consent questions make
  a dataset unrepresentable.
