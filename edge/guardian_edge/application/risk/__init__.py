"""Risk engine application layer (ADR-0013).

Consumes candidate events (as a plain EventConsumer — the event engine is
untouched) and converts them into SafetyIncidents: correlated, severity-
rated, false-positive-suppressed, and always awaiting human review. The
notification engine attaches downstream as an IncidentConsumer; humans
remain the only deciders (docs/04).
"""
