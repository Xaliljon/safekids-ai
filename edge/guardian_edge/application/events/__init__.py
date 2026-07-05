"""Event engine application layer (ADR-0012).

Consumes tracking results (as a plain TrackConsumer — the vision pipeline
is untouched), maintains per-track motion history, and generates
explainable candidate safety events. Candidates are suspicions with
signals attached, not alerts: the future risk engine decides what reaches
humans, and humans decide what is true (docs/04).

Pure Python — no tensor libraries; every feature is arithmetic over
normalized track geometry.
"""
