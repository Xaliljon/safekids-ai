# ADR-0009: Model Management and OTA Layout

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Models will reach deployed Guardian Edge Boxes over the air, unattended, in
kindergartens. A bad model update must be recoverable in seconds without
re-downloading anything; a corrupted or tampered bundle must never activate;
and a model whose license the company cannot ship (the ADR-0003 AGPL risk)
must be impossible to install even by accident. Sprint 6 builds the store
these guarantees live in — the model zoo — on top of the ADR-0008 registry
layout.

## Decision

1. **Installed versions are immutable.** A version directory
   (`<root>/<name>/<version>/`) is written once and never modified;
   re-shipping a fix means shipping a new version. Every deployed box with
   version X has bit-identical artifacts, and rollback targets can be
   trusted not to have drifted.

2. **Installs are staged and atomic.** Bundles are validated, copied into
   `<root>/.staging/`, then `rename(2)`d into place — on one filesystem the
   rename is atomic, so a crash or power loss mid-install leaves either no
   model or a complete model, never a torn one. Stale staging debris is
   swept at zoo startup, and the registry never lists staged content.

3. **Five gates before anything lands** (a refused install leaves no
   trace): manifest parses strictly → **checksum is mandatory** at install
   time (the registry tolerates legacy checksum-less manifests with a loud
   warning; the zoo does not) and must match the artifact → **license
   allowlist** passes → **compatibility** passes (manifest schema
   generation known, `min_edge_version` ≤ this runtime) → only then copy.

4. **License policy is enforced on-device, at install time.** The default
   allowlist is permissive licenses plus our own proprietary identifier
   (`Apache-2.0`, `MIT`, `BSD-2/3-Clause`, `Proprietary-GuardianAI`).
   Undeclared licenses are refused outright. This makes the ADR-0003
   failure mode — AGPL weights reaching a proprietary product — a
   structural impossibility rather than a process hope.

5. **Activation is a pointer, rollback is a pointer swap.** Each model
   directory holds an atomically-written `state.json` with `active` and
   `previous` versions. `ModelRegistry.get(name)` resolves the active
   version first (newest semver only when nothing was ever activated).
   Rollback verifies the previous version still passes checksum, then
   swaps the pointers — no deletion, no re-download, reversible. The
   active version cannot be removed.

6. **Versions are strict SemVer**, parsed and ordered by a domain
   `ModelVersion` (releases outrank prereleases; `1.10.0 > 1.2.0`).
   Manifests with non-semver versions are invalid everywhere.

7. **Bundle = manifest + artifact; signing lives one layer down.** The OTA
   agent (firmware) downloads a bundle, verifies its *signature*, then
   drives the `ModelZoo` port (`install(activate=True)`, `rollback` on
   failed health checks). The zoo verifies *integrity and policy*;
   authenticity is the firmware layer's job (ADR-0001 CD: signed, pull-
   based, rollback-safe updates).

## Consequences

- The health-check-driven OTA loop becomes trivial: install → activate →
  watch → `rollback()` — seconds, offline-capable, no network needed.
- Disk usage grows with retained versions; `remove()` exists for pruning
  (never the active version), and a retention policy can sit on top later.
- Legacy checksum-less models keep loading via the registry (warned) but
  can never enter a device through the zoo — the strictness gradient is
  deliberate during the transition.
- `ai/export` must emit `license` and `compatibility` in every manifest;
  the contracts/models schema gains both fields.

## Alternatives Considered

- **`current` symlinks instead of a state file:** rejected — symlinks
  carry no `previous` pointer for rollback, behave inconsistently across
  filesystems, and a JSON state file is greppable and auditable.
- **In-place upgrade of a version directory:** rejected — mutable versions
  make "what is running on this box?" unanswerable and rollback targets
  untrustworthy.
- **Optional checksums at install:** rejected — an unverifiable artifact
  on a child-safety device is not a corner worth cutting; legacy leniency
  stays confined to the read path.
- **License checking only in CI/ai-export:** rejected — process gates fail
  silently under pressure; the device refusing the bundle cannot be
  forgotten.
- **Signature verification inside the zoo:** rejected for now — key
  management belongs to the firmware/OTA layer where secure storage lives;
  duplicating it here would blur the trust boundary.
