# adr/

Architecture Decision Records — the memory of *why* the system is shaped the
way it is (docs/03 §9: documentation explains decisions).

## Process

1. Copy `TEMPLATE.md` to `ADR-NNNN-short-title.md` (next free number).
2. Open a PR; the decision is discussed **before** implementation.
3. Status flows: `Proposed → Accepted` (or `Superseded by ADR-XXXX` later). ADRs are never deleted or rewritten — supersede them.

## When an ADR is required

- Any decision with multi-year consequences (technology, boundary, data, security)
- Anything that changes a rule in ADR-0001
- Anything a future engineer would ask "why on earth…?" about

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001-monorepo-architecture.md) | Monorepo Architecture | Accepted |
| ADR-0002 | Dashboard technology (folded into ADR-0001 §8) | — |
| ADR-0003 | Object detector selection & licensing (AGPL risk) | **Needed before first AI code** |
| ADR-0004 | Edge/cloud responsibility split | Planned |
| ADR-0005 | Dataset governance | **Needed before first data collection** |
