# Model Management (Model Zoo)

- **Date:** 2026-07-05 (Sprint 6)
- **Reflects:** ADR-0008 (runtime contracts), ADR-0009 (management & OTA layout)
- **Scope:** the managed model store — no models, no detectors, no task logic

## Purpose

Everything between "a model bundle arrives on the box" and "the registry
serves it": validated atomic installs, activation, rollback. The zoo is the
write path; the ADR-0008 registry stays the read path over the same layout.

## On-disk layout (OTA-ready)

```
models/
  .staging/                     # in-flight installs; swept at startup, never listed
  fall-detector/
    state.json                  # {"active": "1.1.0", "previous": "1.0.0"} — atomic writes
    1.0.0/
      manifest.json
      model.onnx
    1.1.0/
      manifest.json
      model.onnx
```

- **Versions are immutable** — written once via staged copy + atomic rename;
  a crash mid-install leaves no model or a whole model, never a torn one.
- **`state.json`** carries the activation pointer and the rollback target.
  `ModelRegistry.get(name)` resolves `active` first; newest semver applies
  only when nothing was ever activated.

## Install pipeline — five gates, no trace on refusal

```
bundle dir (manifest.json + artifact)
   │ 1. manifest parses strictly (schema, semver version)
   │ 2. sha256 declared AND matches artifact          -> ModelInstallError
   │ 3. license in on-device allowlist                -> ModelLicenseError
   │ 4. compatible (schema gen, min_edge_version)     -> ModelCompatibilityError
   │ 5. staged copy -> atomic rename into place
   └─ optional: activate (pointer switch)
```

## License policy (requirement of ADR-0009 §4)

`LicensePolicy` — allowlist enforced **on the device at install time**:
`Apache-2.0`, `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Proprietary-GuardianAI`.
Undeclared → refused. AGPL (the ADR-0003 risk) → refused structurally,
not procedurally.

## Compatibility checks

Manifests declare a `compatibility` block:

```json
{ "compatibility": { "schema": 1, "min_edge_version": "0.1.0" } }
```

`CompatibilityChecker` refuses unknown manifest schema generations and
models requiring a newer `guardian-edge` than the device runs — an OTA
push can never brick inference on an older box.

## Version management & rollback

- `ModelVersion` (domain): strict SemVer, numeric ordering
  (`1.10.0 > 1.2.0`), releases outrank prereleases.
- `activate(name, version)` verifies the target (existence + checksum)
  then swaps pointers; `previous` is preserved.
- `rollback(name)` re-verifies the previous version and swaps back —
  reversible, offline, no re-download. The active version cannot be
  `remove()`d.

## The OTA loop (future firmware agent)

```
download bundle -> verify SIGNATURE (firmware layer, key storage)
  -> zoo.install(bundle, activate=True)     # integrity + policy gates here
  -> run health checks on live inference
  -> healthy? done : zoo.rollback(name)     # seconds, pointer swap
```

Authenticity is the firmware layer's job; the zoo owns integrity and
policy. The layout above is exactly what signed OTA bundles ship into.

## Testing approach

50 unit tests over synthetic bundles: tampered artifacts (refused, no
trace), AGPL/undeclared licenses, incompatible runtimes, immutability,
pointer semantics (active beats latest), reversible rollback, history
clearing on removal, crash-debris sweep, and staging never leaking into
the registry.

## Out of scope (later)

Bundle signature verification (firmware layer), retention/pruning policy,
delta updates, remote zoo synchronization with the backend.
