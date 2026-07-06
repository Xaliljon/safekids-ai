"""Evidence infrastructure: ring buffers, overlay rendering, encrypted store.

Everything here composes over the frozen pipeline through its public seams
(FrameConsumer, TrackConsumer, IncidentConsumer). Nothing in this package
is ever on the AI hot path — the buffers accept work without blocking and
all heavy lifting (JPEG decode, overlay drawing, mp4 encode, encryption)
happens on background threads (ADR-0017).
"""
