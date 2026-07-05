# ADR-0001: Monorepo Architecture

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Guardian AI spans five loosely coupled domains — AI (model development), Edge runtime,
Backend, Mobile, and Dashboard — plus hardware/firmware. The engineering principles
(docs/03) mandate Clean Architecture, modular design, and ten-year maintainability.
The team is small; tooling overhead must stay near zero while coupling between
domains must stay impossible by construction, not by discipline alone.

## Decision

One monorepo with component-per-directory, connected only through `contracts/`:

1. **`contracts/` is the single source of truth for every boundary** (OpenAPI specs,
   event JSON Schemas, model manifests). Clients and schemas are code-generated;
   handwritten cross-component models are forbidden.
2. **`edge/` is a first-class component**, separate from `ai/`. `ai/` produces
   versioned model artifacts (ONNX + manifest); `edge/` consumes them. The dependency
   is an artifact boundary, never a code import.
3. **Each app carries its own Clean Architecture layers** (domain → application →
   infrastructure/presentation, dependencies pointing inward). No global layering.
4. **Cross-app imports are forbidden.** Shared code is promoted deliberately into
   `packages/dart/*` or `packages/python/guardian_common`.
5. **Edge is offline-capable by definition**; cloud sync is optional metadata-only.
   Backend never receives raw video streams.
6. **Boring build tooling**: uv workspace for Python, per-package Flutter/Dart with
   Makefile orchestration, Docker Compose for local services, path-filtered GitHub
   Actions. No Bazel/Nx-class build systems at this team size.
7. **ONNX is the canonical model format**; TensorRT is one inference backend behind
   an interface (Jetson), ONNX Runtime is another (Intel N100, dev machines).
8. **Dashboard is Flutter Web** so `guardian_core`, `guardian_api_client`, and
   `guardian_ui` are shared with mobile. (Revisit via a superseding ADR only if
   Flutter Web performance proves inadequate for dashboard workloads.)
9. **Git workflow** per docs/03: `main ← develop ← feature/*`, Conventional Commits
   with component scopes, component-scoped release tags (`backend-v1.2.0`).
10. **Raw datasets and model weights never enter git** — DVC pointers only;
    enforced by .gitignore, pre-commit large-file hook, and CI.

## Consequences

- Coupling between the five domains is structurally prevented; each can be
  extracted into its own repo later without surgery.
- Contract changes are reviewed before implementation, making breaking changes
  visible at PR time (oasdiff gate once specs exist).
- Cost: codegen discipline and contract-first workflow are a tax on small changes.
  Accepted as the price of ten-year maintainability.
- Jetson-specific behavior is not covered by hosted CI; a self-hosted bench-Jetson
  nightly job is required before pilot deployment.

## Alternatives Considered

- **Polyrepo (repo per component):** rejected — cross-cutting changes (event schema
  touches edge + backend + mobile) become multi-repo choreography for a small team.
- **Global Clean Architecture layering across the monorepo:** rejected — forces
  artificial dependencies between unrelated apps; layers belong inside each app.
- **Bazel/Nx unified build:** rejected — unnecessary complexity (docs/03 §1).
- **React/Next.js dashboard:** rejected for now — splits the front-end stack and
  doubles design-system and client maintenance for one team.
- **Edge runtime inside `ai/`:** rejected — couples training to serving and makes
  the most safety-critical deployable a subfolder of a research area.
