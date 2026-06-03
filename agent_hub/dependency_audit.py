from __future__ import annotations

import ast
import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


INTERNAL_TOP_LEVEL = {"agent_hub", "scripts"}
RELEASE_EXTRA_DEPENDENCIES = {"build", "packaging"}


def load_pyproject(root: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def declared_project_dependencies(pyproject: dict[str, Any]) -> list[str]:
    project = pyproject.get("project") if isinstance(pyproject, dict) else {}
    dependencies = project.get("dependencies") if isinstance(project, dict) else []
    if not isinstance(dependencies, list):
        return []
    return [str(item) for item in dependencies if isinstance(item, str)]


def declared_optional_dependencies(pyproject: dict[str, Any], extra: str) -> list[str]:
    project = pyproject.get("project") if isinstance(pyproject, dict) else {}
    optional = project.get("optional-dependencies") if isinstance(project, dict) else {}
    dependencies = optional.get(extra) if isinstance(optional, dict) else []
    if not isinstance(dependencies, list):
        return []
    return [str(item) for item in dependencies if isinstance(item, str)]


def runtime_import_names(root: Path) -> set[str]:
    package_root = root / "agent_hub"
    imports: set[str] = set()
    for path in package_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        imports.update(_top_level_imports(path))
    return {
        name
        for name in imports
        if name
        and name not in INTERNAL_TOP_LEVEL
        and name not in sys.stdlib_module_names
    }


def runtime_dependency_audit(root: Path, pyproject: dict[str, Any] | None = None) -> dict[str, Any]:
    pyproject = pyproject if pyproject is not None else load_pyproject(root)
    imports = runtime_import_names(root)
    declared_dependencies = declared_project_dependencies(pyproject)
    declared = {
        dependency_import_name(dependency)
        for dependency in declared_dependencies
    }
    return {
        "runtime_imports": sorted(imports),
        "declared_runtime_dependencies": sorted(declared),
        "declared_runtime_dependency_specs": declared_dependencies,
        "missing": sorted(imports - declared),
        "extra": sorted(declared - imports),
    }


def dependency_install_checks(root: Path) -> list[dict[str, Any]]:
    pyproject = load_pyproject(root)
    if not pyproject:
        return [
            {
                "id": "runtime_dependency_audit",
                "category": "dependency",
                "ok": False,
                "detail": "Could not read pyproject.toml",
            }
        ]

    audit = runtime_dependency_audit(root, pyproject)
    rows = [
        {
            "id": "runtime_dependency_audit",
            "category": "dependency",
            "ok": not audit["missing"] and not audit["extra"],
            "detail": _audit_detail(audit),
        }
    ]
    for dependency in declared_project_dependencies(pyproject):
        module = dependency_import_name(dependency)
        rows.append(
            {
                "id": f"dependency:{module}",
                "category": "dependency",
                "ok": importlib.util.find_spec(module) is not None,
                "detail": dependency,
            }
        )
    for dependency in declared_optional_dependencies(pyproject, "release"):
        module = dependency_import_name(dependency)
        rows.append(
            {
                "id": f"release_dependency:{module}",
                "category": "dependency",
                "ok": importlib.util.find_spec(module) is not None,
                "optional": True,
                "detail": dependency,
            }
        )
    return rows


def validate_dependency_declarations(root: Path, pyproject: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    audit = runtime_dependency_audit(root, pyproject)
    if not audit["declared_runtime_dependency_specs"]:
        failures.append("pyproject.toml project.dependencies must not be empty")
    for name in audit["missing"]:
        failures.append(f"pyproject.toml project.dependencies is missing runtime dependency for import {name}")
    for name in audit["extra"]:
        failures.append(f"pyproject.toml project.dependencies declares unused runtime dependency {name}")

    release = {
        dependency_import_name(dependency)
        for dependency in declared_optional_dependencies(pyproject, "release")
    }
    for name in sorted(RELEASE_EXTRA_DEPENDENCIES - release):
        failures.append(f"pyproject.toml release extra is missing {name}")
    return failures


def dependency_import_name(dependency: str) -> str:
    name = re.split(r"[<>=!~;\[]", dependency, maxsplit=1)[0].strip()
    return name.replace("-", "_")


def _top_level_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _audit_detail(audit: dict[str, Any]) -> str:
    if audit["missing"]:
        return "missing: " + ", ".join(audit["missing"])
    if audit["extra"]:
        return "unused: " + ", ".join(audit["extra"])
    imports = audit["runtime_imports"]
    return "runtime imports: " + (", ".join(imports) if imports else "stdlib only")
