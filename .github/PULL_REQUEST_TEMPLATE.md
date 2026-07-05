# Pull Request

## Why is this change necessary?

<!-- Link the doc/ADR/issue that motivates it. Documentation first. -->

## What problem does it solve?

## Does it respect project principles?

<!-- docs/03_ENGINEERING_PRINCIPLES.md and docs/04_AI_ETHICS.md -->

## Could it be simpler?

---

## Checklist

- [ ] Documentation updated (or no doc change needed)
- [ ] Tests added/updated (unit, integration, edge cases)
- [ ] No secrets, tokens, or environment-specific values in code
- [ ] No privacy-sensitive data in logs or test fixtures (child data is radioactive)
- [ ] Public API changes go through `contracts/` and are backward compatible
- [ ] Architecture layers respected (dependencies point inward; no cross-app imports)
