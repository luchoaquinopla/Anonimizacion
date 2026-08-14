"""Fixtures compartidas de pytest. Todo dato de fixture debe ser sintético (ver AGENTS.md)."""

from __future__ import annotations

import sys
from pathlib import Path

# permite correr tests sin instalación editable (layout `src`)
RAIZ_SRC = Path(__file__).resolve().parent.parent / "src"
if str(RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(RAIZ_SRC))
