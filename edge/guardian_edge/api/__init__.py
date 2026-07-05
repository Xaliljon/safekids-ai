"""Guardian Device API: the box's local-network surface (ADR-0015).

Pairing, realtime notification push (WebSocket), offline catch-up from the
durable outbox, and incident review actions — pure composition over the
existing engines; none of them is modified or aware of this layer.
"""
