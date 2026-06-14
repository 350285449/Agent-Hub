from __future__ import annotations

from pathlib import Path


def detect_test_framework(root: str | Path) -> str:
    root = Path(root)
    names = {path.name.lower() for path in root.rglob("*") if path.is_file()}
    if "pytest.ini" in names or any(path.name.startswith("test_") and path.suffix == ".py" for path in root.rglob("*.py")):
        return "pytest"
    if "tox.ini" in names:
        return "pytest/tox"
    if any(name in names for name in ("jest.config.js", "vitest.config.ts", "vitest.config.js")):
        return "jest/vitest"
    if "package.json" in names:
        try:
            package = (root / "package.json").read_text(encoding="utf-8").lower()
        except OSError:
            package = ""
        if "vitest" in package:
            return "vitest"
        if "jest" in package:
            return "jest"
    if any(path.name.endswith("_test.go") for path in root.rglob("*.go")):
        return "go test"
    return "unknown"
