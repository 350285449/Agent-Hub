from __future__ import annotations

from pathlib import Path

from .dependency_detector import detect_package_manager, read_package_dependencies
from .dna_profile import RepoDNAProfile
from .framework_detector import detect_framework, detect_language
from .style_detector import detect_style
from .test_detector import detect_test_framework


def scan_repository(root: str | Path) -> RepoDNAProfile:
    root = Path(root)
    style = detect_style(root)
    dependencies = sorted(read_package_dependencies(root))
    important = _important_files(root)
    risky = _risky_files(root)
    architecture = _architecture_pattern(root)
    return RepoDNAProfile(
        language=detect_language(root),
        framework=detect_framework(root),
        test_framework=detect_test_framework(root),
        package_manager=detect_package_manager(root),
        architecture_pattern=architecture,
        naming_style=str(style.get("naming_style") or "unknown"),
        lint_tools=list(style.get("lint_tools") or []),
        formatting_tools=list(style.get("formatting_tools") or []),
        dependencies=dependencies[:50],
        important_files=important,
        risky_files=risky,
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:100_000]
    except OSError:
        return ""


def _architecture_pattern(root: Path) -> str:
    py_files = [path for path in _iter_repo_files(root) if path.suffix == ".py"]
    if any("Depends(" in _read(path) or "dependency_injector" in _read(path) for path in py_files[:300]):
        return "dependency injection"
    if (root / "src").is_dir() and (root / "tests").is_dir():
        return "src layout"
    if any((root / name).is_dir() for name in ("apps", "packages", "services")):
        return "modular monorepo"
    if (root / "agent_hub").is_dir() and (root / "vscode-extension").is_dir():
        return "backend plus VS Code extension"
    return "modular"


def _important_files(root: Path) -> list[str]:
    names = (
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "README.md",
        "agent-hub.config.json",
        "Dockerfile",
        "docker-compose.yml",
        "pytest.ini",
        "ruff.toml",
    )
    found = [
        str(path.relative_to(root))
        for name in names
        for path in [root / name]
        if path.exists()
    ]
    for directory in ("tests", "src", "agent_hub", "vscode-extension"):
        path = root / directory
        if path.exists():
            found.append(str(path.relative_to(root)))
    return found[:50]


def _risky_files(root: Path) -> list[str]:
    risky_names = {"server.py", "extension.js", "selection.py", ".env", "settings.json"}
    rows: list[tuple[int, str]] = []
    for path in _iter_repo_files(root):
        rel = str(path.relative_to(root))
        lower = rel.lower().replace("\\", "/")
        score = 0
        if path.name.lower() in risky_names:
            score += 8
        if any(part in lower for part in ("/migrations/", "/security/", "/permissions", "/routing/", "/api/")):
            score += 4
        if path.suffix in {".env", ".key", ".pem"}:
            score += 10
        try:
            if path.stat().st_size > 150_000:
                score += 2
        except OSError:
            pass
        if score:
            rows.append((score, rel))
    return [rel for _score, rel in sorted(rows, key=lambda item: (-item[0], item[1]))[:25]]


def _iter_repo_files(root: Path):
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
    for path in root.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            yield path
