"""Evidence application layer: incident-driven clip export and retention.

Attaches to the frozen pipeline through the IncidentConsumer seam — the
Risk Engine never waits for evidence; export runs on background threads
(ADR-0017).
"""
