# research/

Experiments, notebooks, and prototypes. Free-form by design — this is the only
directory where scaffolding rules are relaxed so ideas can move fast.

## The graduation rule

Nothing ships from here. An experiment graduates into `ai/` via a PR that includes:

1. Evaluation results (accuracy, FP/FN rate, latency, robustness — docs/04 metric set)
2. The AI ethics checklist from `docs/04_AI_ETHICS.md`
3. Clean, tested code conforming to repo standards

## Still non-negotiable, even here

- No raw child data in git (use DVC pointers; see `datasets/README.md`).
- No credentials or secrets in notebooks.
- Research directions follow docs/01 (Edge AI, action recognition, pose estimation, privacy-preserving AI, TinyML, explainable AI).
