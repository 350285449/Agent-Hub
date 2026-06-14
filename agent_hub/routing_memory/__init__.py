from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_LEGACY_PATH = Path(__file__).resolve().parent.parent / "routing_memory.py"
_SPEC = importlib.util.spec_from_file_location("agent_hub._routing_memory_legacy", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load routing memory from {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _legacy
_SPEC.loader.exec_module(_legacy)

for _name in getattr(_legacy, "__all__", []):
    globals()[_name] = getattr(_legacy, _name)

__all__ = list(getattr(_legacy, "__all__", []))
