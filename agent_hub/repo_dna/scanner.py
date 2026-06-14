from __future__ import annotations

from pathlib import Path
import ast
import json
import re

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
    architecture_fingerprint = _architecture_fingerprint(root)
    coding_style_fingerprint = _coding_style_fingerprint(root)
    symbol_graph = _symbol_graph(root)
    import_graph = _import_graph(root)
    dependency_graph = _dependency_graph(root, dependencies)
    profile = RepoDNAProfile(
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
        architecture_fingerprint=architecture_fingerprint,
        coding_style_fingerprint=coding_style_fingerprint,
        symbol_graph=symbol_graph,
        import_graph=import_graph,
        dependency_graph=dependency_graph,
    )
    _write_repo_dna(root, profile)
    return profile


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


def _architecture_fingerprint(root: Path) -> list[str]:
    paths = [str(path.relative_to(root)).replace("\\", "/").lower() for path in _iter_repo_files(root)]
    dirs = {part for rel in paths for part in rel.split("/")[:-1]}
    joined = "\n".join(paths[:2000])
    found: list[str] = []
    if {"controllers", "models", "views"} <= dirs or re.search(r"/controllers?/", joined):
        found.append("MVC")
    if {"domain", "application", "infrastructure"} <= dirs or "adapters/" in joined and "ports/" in joined:
        found.append("hexagonal")
    if {"domain", "use_cases"} & dirs and {"entities", "interfaces"} & dirs:
        found.append("clean architecture")
    if any(rel.startswith(("services/", "apps/")) for rel in paths) or "docker-compose.yml" in paths:
        found.append("microservices" if _service_count(root) >= 2 else "monolith")
    elif any(name in dirs for name in ("src", "agent_hub", "app")):
        found.append("monolith")
    if any(part in dirs for part in ("domain", "aggregates", "value_objects")):
        found.append("DDD")
    return found or ["modular"]


def _coding_style_fingerprint(root: Path) -> list[str]:
    text = "\n".join(_read(path) for path in list(_iter_repo_files(root))[:500] if path.suffix in {".py", ".js", ".ts", ".tsx", ".java", ".cs"})
    found: list[str] = []
    if re.search(r"class\s+\w*Service\b|class\s+\w+.*Service", text):
        found.append("service classes")
    if re.search(r"\b(map|filter|reduce)\s*\(|lambda\s+|=>", text):
        found.append("functional style")
    if "Depends(" in text or "dependency_injector" in text or re.search(r"constructor\s*\([^)]*\w+Service", text):
        found.append("dependency injection")
    if re.search(r"class\s+\w*Factory\b|\bcreate_\w+\(|\bmake_\w+\(", text):
        found.append("factory patterns")
    if re.search(r"class\s+\w*Repository\b|/repositories?/|repository\.", text, re.I):
        found.append("repository patterns")
    return found or ["direct procedural style"]


def _symbol_graph(root: Path) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for path in list(_iter_repo_files(root))[:400]:
        if path.suffix != ".py":
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            tree = ast.parse(_read(path))
        except SyntaxError:
            continue
        symbols = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if symbols:
            graph[rel] = symbols[:80]
    return graph


def _import_graph(root: Path) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for path in list(_iter_repo_files(root))[:500]:
        rel = str(path.relative_to(root)).replace("\\", "/")
        imports: list[str] = []
        if path.suffix == ".py":
            try:
                tree = ast.parse(_read(path))
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module.split(".")[0])
        elif path.suffix in {".js", ".ts", ".tsx"}:
            imports.extend(re.findall(r"from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\)", _read(path)))
            imports = [item for pair in imports for item in (pair if isinstance(pair, tuple) else (pair,)) if item]
        if imports:
            graph[rel] = sorted(set(imports))[:80]
    return graph


def _dependency_graph(root: Path, dependencies: list[str]) -> dict[str, list[str]]:
    graph = {"root": dependencies[:100]}
    for manifest in ("pyproject.toml", "package.json", "requirements.txt", "build.gradle"):
        if (root / manifest).exists():
            graph[manifest] = dependencies[:100]
    return graph


def _service_count(root: Path) -> int:
    names = {"package.json", "pyproject.toml", "pom.xml", "build.gradle", "Dockerfile"}
    return sum(1 for path in _iter_repo_files(root) if path.name in names and len(path.relative_to(root).parts) > 1)


def _write_repo_dna(root: Path, profile: RepoDNAProfile) -> None:
    try:
        state = root / ".agent-hub"
        state.mkdir(parents=True, exist_ok=True)
        (state / "repo_dna.json").write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    except OSError:
        return


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
