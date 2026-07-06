"""Guardian annotation tool: a local web page over a headless session.

No cloud dependency — a stdlib HTTP server on localhost serves frames
and applies edits; all annotation logic (undo/redo, autosave, Guardian
export) lives in :class:`AnnotationSession`, fully testable without a
browser.
"""

from __future__ import annotations

from guardian_ai.acquisition.annotator.session import AnnotationSession

__all__ = ["AnnotationSession"]
