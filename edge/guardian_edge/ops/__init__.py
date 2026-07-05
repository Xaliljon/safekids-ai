"""Operations layer (ADR-0016): everything a pilot box needs to be
installed, monitored, diagnosed and recovered without a developer.

Pure composition over the frozen engines — health, diagnostics, watchdog,
backup, logging and performance monitoring observe and restart components
through their existing public APIs; nothing here reaches into engine
internals.
"""
