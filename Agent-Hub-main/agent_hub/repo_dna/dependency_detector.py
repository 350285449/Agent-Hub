from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def detect_package_manager(root: str | Path) -> str:
    root = Path(root)
    if (root / "uv.lock").exists():
        return "uv"
    if (root / "poetry.lock").exists():
        return "poetry"
    if (root / "Pipfile").exists():
        return "pipenv"
    if (root / "package-lock.json").exists():
        return "npm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "pip"
    if (root / "go.mod").exists():
        return "go"
    if (root / "Cargo.toml").exists():
        return "cargo"
    return "unknown"


def read_package_dependencies(root: str | Path) -> set[str]:
    root = Path(root)
    deps: set[str] = set()
    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                deps.update(str(key).lower() for key in dict(data.get(section) or {}).keys())
        except (OSError, json.JSONDecodeError):
            pass
    requirements = root / "requirements.txt"
    if requirements.exists():
        try:
            for line in requirements.read_text(encoding="utf-8").splitlines():
                name = re.split(r"[<>=~!;\[]", line.strip(), maxsplit=1)[0].strip().lower()
                if name and not name.startswith("#"):
                    deps.add(name)
        except OSError:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""
        deps.update(_pyproject_dependencies(text))
        lowered = text.lower()
        for known in (
            "fastapi",
            "pydantic",
            "pytest",
            "ruff",
            "black",
            "django",
            "flask",
            "sqlalchemy",
            "typer",
            "click",
            "mypy",
        ):
            if known in lowered:
                deps.add(known)
    return deps


def _pyproject_dependencies(text: str) -> set[str]:
    deps: set[str] = set()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        data = {}
    project = data.get("project") if isinstance(data, dict) else {}
    if isinstance(project, dict):
        deps.update(_dependency_names(project.get("dependencies")))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for values in optional.values():
                deps.update(_dependency_names(values))
    tool = data.get("tool") if isinstance(data, dict) else {}
    poetry = tool.get("poetry") if isinstance(tool, dict) and isinstance(tool.get("poetry"), dict) else {}
    for section in ("dependencies", "group"):
        value = poetry.get(section) if isinstance(poetry, dict) else None
        if isinstance(value, dict):
            deps.update(str(key).lower() for key in value if str(key).lower() != "python")
    # Keep a permissive fallback so partially invalid pyproject files still yield hints.
    deps.update(
        name.lower()
        for name in re.findall(r"['\"]([a-zA-Z0-9_.-]+)(?:[<>=~!\[].*)?['\"]", text)
        if name and not name.startswith(".")
    )
    return deps


def _dependency_names(values: object) -> set[str]:
    deps: set[str] = set()
    if not isinstance(values, list):
        return deps
    for value in values:
        name = re.split(r"[<>=~!;\[]", str(value).strip(), maxsplit=1)[0].strip().lower()
        if name:
            deps.add(name)
    return deps
