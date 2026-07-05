# architecture/

System design artifacts: C4 diagrams (context, container, component), data-flow
diagrams, sequence diagrams for the alert pipeline, deployment topologies.

## Conventions

- Diagrams as code where possible (Mermaid/PlantUML in Markdown) so they diff in PRs.
- Every diagram states its date and the ADRs it reflects — a diagram that contradicts an accepted ADR is a bug.
- Decisions live in `/adr`; this directory shows the *resulting shape*, not the reasoning.

## Planned artifacts

- `system-context.md` — C4 level 1: Guardian AI platform and its actors
- `container-diagram.md` — C4 level 2: edge box, backend, mobile, dashboard, contracts
- `alert-pipeline.md` — sequence: camera → inference → risk → event → notification → human review (< 1 s budget)
- `deployment.md` — kindergarten LAN topology, offline mode, optional cloud
