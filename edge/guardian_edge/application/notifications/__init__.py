"""Notification engine application layer (ADR-0014).

Consumes SafetyIncidents (as a plain IncidentConsumer — the risk engine is
untouched) and delivers metadata-only notifications through pluggable
channels with queueing, exponential retry, and metrics. Contains no AI
logic and no risk logic: severity in, delivery out.
"""
