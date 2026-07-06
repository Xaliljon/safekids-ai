"""Official Apache-2.0 YOLOX, wrapped — never forked, never modified.

``pip``/``uv`` install the real ``megvii-basedetection/YOLOX`` package
(pinned commit, see the workspace root ``pyproject.toml``'s
``[tool.uv.sources]``); everything in this package is *our* adapter code
translating between Guardian's ``DetectorFamily`` port and YOLOX's own
calling convention. No upstream source file is copied or edited here.
"""

from __future__ import annotations

from guardian_ai.training.detectors.yolox.family import OfficialYoloxTrainer

__all__ = ["OfficialYoloxTrainer"]
