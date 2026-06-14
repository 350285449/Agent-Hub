from __future__ import annotations

from pathlib import Path


def detect_style(root: str | Path) -> dict[str, object]:
    root = Path(root)
    files = {path.name.lower() for path in root.iterdir() if path.is_file()}
    lint_tools = []
    formatting_tools = []
    if "ruff.toml" in files or "pyproject.toml" in files:
        text = _read(root / "pyproject.toml").lower()
        if "ruff" in text:
            lint_tools.append("ruff")
            formatting_tools.append("ruff")
        if "black" in text:
            formatting_tools.append("black")
    if any(name.startswith(".eslintrc") or name == "eslint.config.js" for name in files):
        lint_tools.append("eslint")
    if any(name.startswith(".prettierrc") or name == "prettier.config.js" for name in files):
        formatting_tools.append("prettier")
    if "mypy.ini" in files or "pyrightconfig.json" in files:
        lint_tools.append("type-checking")
    if "biome.json" in files:
        lint_tools.append("biome")
        formatting_tools.append("biome")
    python_count = len([path for path in _iter_files(root) if path.suffix == ".py"])
    js_count = len([path for path in _iter_files(root) if path.suffix in {".js", ".jsx", ".ts", ".tsx"}])
    return {
        "naming_style": "snake_case" if python_count >= js_count else "camelCase",
        "lint_tools": sorted(set(lint_tools)),
        "formatting_tools": sorted(set(formatting_tools)),
    }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _iter_files(root: Path):
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
    for path in root.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            yield path
