from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import HubRequest
from .workspace_safety import MAX_REPO_MAP_FILES, MAX_SYMBOLS_PER_FILE, _dedupe


def _request_text_for_paths(request: HubRequest) -> str:
    parts: list[str] = []
    if request.task:
        parts.append(str(request.task))
    if request.context:
        parts.append(str(request.context))
    for message in request.messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _short_task_focus(request: HubRequest) -> str:
    text = _request_text_for_paths(request)
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    return " ".join(words[:12])[:160] or "workspace"


def _path_like_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    pattern = re.compile(
        r"(?<![A-Za-z0-9_./\\-])"
        r"([A-Za-z0-9_.-]+(?:[/\\][A-Za-z0-9_.-]+)+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8})"
    )
    for match in pattern.finditer(text):
        token = match.group(1).strip().strip(".,:;()[]{}\"'")
        if token and token not in {".", ".."} and token not in tokens:
            tokens.append(token)
    return tokens[:30]


def _is_probably_text_file(path: Path) -> bool:
    if path.name.lower() in {
        "makefile",
        "dockerfile",
        "license",
        "readme",
    }:
        return True
    return path.suffix.lower() in {
        ".bat",
        ".cfg",
        ".css",
        ".env",
        ".go",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".ps1",
        ".py",
        ".rs",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }


def _is_config_file(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered in {
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "tox.ini",
        "tsconfig.json",
        "eslint.config.js",
        "vite.config.js",
        "webpack.config.js",
        "agent-hub.config.json",
    }:
        return True
    return path.suffix.lower() in {".toml", ".yaml", ".yml", ".ini", ".cfg"}


def _is_test_file(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".spec.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
    )


def _file_symbols(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    symbols: list[str] = []
    patterns = [
        re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", re.MULTILINE),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            symbol = match.group(1)
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= MAX_SYMBOLS_PER_FILE:
                return symbols
    return symbols


def _repo_dependency_map(root: Path, related_files: list[str]) -> tuple[dict[str, list[str]], list[str], list[str]]:
    dependency_map: dict[str, list[str]] = {}
    dependency_files: list[str] = []
    import_hints: list[str] = []
    for relative in related_files:
        source = root / relative
        dependencies = _file_dependencies(source)
        resolved: list[str] = []
        for dependency in dependencies:
            resolved.extend(_resolve_dependency_files(root, relative, dependency))
        resolved = _dedupe(resolved)
        if resolved:
            dependency_map[relative] = resolved
            dependency_files.extend(resolved)
        for dependency in dependencies[:4]:
            hint = dependency.lstrip(".")
            if hint and not hint.startswith(("/", "\\")):
                import_hints.append(f"search_files query: {hint.split('.')[-1]}")
    return dependency_map, _dedupe(dependency_files), _dedupe(import_hints)


def _reverse_dependency_map(root: Path, files: list[str]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {}
    for relative in files:
        dependencies = _file_dependencies(root / relative)
        for dependency in dependencies:
            for resolved in _resolve_dependency_files(root, relative, dependency):
                reverse.setdefault(resolved, []).append(relative)
    return {
        path: _dedupe(dependents)[:MAX_REPO_MAP_FILES]
        for path, dependents in reverse.items()
        if dependents
    }


def _symbol_index(root: Path, files: list[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for relative in files[:MAX_REPO_MAP_FILES]:
        path = root / relative
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
            continue
        symbols = _file_symbols(path)
        if symbols:
            index[relative] = symbols
    return index


def _reference_hints(
    focus: str,
    symbol_index: dict[str, list[str]],
    reverse_dependency_map: dict[str, list[str]],
) -> list[str]:
    hints: list[str] = []
    focus_stem = Path(focus.replace("\\", "/")).stem
    if focus_stem:
        hints.append(f"search_files query: {focus_stem}")
    for path, symbols in list(symbol_index.items())[:8]:
        for symbol in symbols[:4]:
            hints.append(f"search_files query: {symbol}")
        if path in reverse_dependency_map:
            hints.extend(f"read_file path: {dependent}" for dependent in reverse_dependency_map[path][:4])
    return _dedupe(hints)[:12]


def _repo_validation_targets(
    related: list[str],
    tests: list[str],
    reverse_dependency_map: dict[str, list[str]],
    dependency_files: list[str],
) -> list[str]:
    targets: list[str] = []
    related_names = {Path(path).stem.lower().removeprefix("test_") for path in related[:20]}
    for test in tests:
        stem = Path(test).stem.lower().removeprefix("test_")
        if stem in related_names or any(name and name in stem for name in related_names):
            targets.append(test)
    for path in [*related[:10], *dependency_files[:10]]:
        targets.extend(reverse_dependency_map.get(path, []))
    targets.extend(path for path in related[:10] if _is_test_file(rootless_path(path)))
    return _dedupe(targets)[:MAX_REPO_MAP_FILES]


def rootless_path(path: str) -> Path:
    return Path(path.replace("\\", "/"))


def _file_dependencies(path: Path) -> list[str]:
    if path.suffix.lower() == ".py":
        return _python_dependencies(path)
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        return _javascript_dependencies(path)
    return []


def _python_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    dependencies: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        patterns = [
            re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE),
            re.compile(r"^\s*from\s+(\.*[A-Za-z_][A-Za-z0-9_.]*)\s+import\s+", re.MULTILINE),
        ]
        for pattern in patterns:
            dependencies.extend(match.group(1) for match in pattern.finditer(text))
        return _dedupe(dependencies)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dependencies.extend(alias.name for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * int(node.level or 0)
            if module:
                dependencies.append(prefix + module)
            else:
                dependencies.extend(prefix + alias.name for alias in node.names if alias.name)
    return _dedupe(dependencies)


def _javascript_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    patterns = [
        re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        re.compile(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    ]
    dependencies: list[str] = []
    for pattern in patterns:
        dependencies.extend(match.group(1) for match in pattern.finditer(text))
    return _dedupe(dependencies)


def _resolve_dependency_files(root: Path, source_relative: str, dependency: str) -> list[str]:
    dependency = dependency.strip()
    if not dependency:
        return []
    if dependency.startswith("."):
        return _resolve_relative_dependency(root, source_relative, dependency)
    if dependency.startswith(("/", "\\")):
        return []
    module_path = dependency.replace(".", "/")
    return _existing_dependency_candidates(
        root,
        [
            module_path,
            f"{module_path}.py",
            f"{module_path}/__init__.py",
            f"{module_path}.js",
            f"{module_path}.ts",
            f"{module_path}.tsx",
            f"{module_path}.jsx",
        ],
    )


def _resolve_relative_dependency(root: Path, source_relative: str, dependency: str) -> list[str]:
    source_dir = Path(source_relative.replace("\\", "/")).parent
    if dependency.startswith(("./", "../")):
        base = source_dir / dependency
    else:
        level = len(dependency) - len(dependency.lstrip("."))
        remainder = dependency[level:].replace(".", "/")
        base = source_dir
        for _ in range(max(0, level - 1)):
            base = base.parent
        if remainder:
            base = base / remainder
    normalized = str(base).replace("\\", "/")
    return _existing_dependency_candidates(
        root,
        [
            normalized,
            f"{normalized}.py",
            f"{normalized}/__init__.py",
            f"{normalized}.js",
            f"{normalized}.ts",
            f"{normalized}.tsx",
            f"{normalized}.jsx",
            f"{normalized}/index.js",
            f"{normalized}/index.ts",
            f"{normalized}/index.tsx",
        ],
    )


def _existing_dependency_candidates(root: Path, candidates: list[str]) -> list[str]:
    resolved: list[str] = []
    for candidate in candidates:
        path = (root / candidate).resolve()
        try:
            if path != root and not path.is_relative_to(root):
                continue
        except ValueError:
            continue
        if path.is_file():
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            resolved.append(relative)
    return _dedupe(resolved)


def _repo_search_hints(focus: str, related_files: list[str]) -> list[str]:
    hints: list[str] = []
    focus_stem = Path(focus.replace("\\", "/")).stem
    if focus_stem:
        hints.append(f"search_files query: {focus_stem}")
    for path in related_files[:5]:
        stem = Path(path).stem
        if stem and stem != focus_stem:
            hints.append(f"search_files query: {stem}")
    return _dedupe(hints)[:8]




__all__ = [
    "_request_text_for_paths",
    "_short_task_focus",
    "_path_like_tokens",
    "_is_probably_text_file",
    "_is_config_file",
    "_is_test_file",
    "_file_symbols",
    "_repo_dependency_map",
    "_reverse_dependency_map",
    "_symbol_index",
    "_reference_hints",
    "_repo_validation_targets",
    "rootless_path",
    "_file_dependencies",
    "_python_dependencies",
    "_javascript_dependencies",
    "_resolve_dependency_files",
    "_resolve_relative_dependency",
    "_existing_dependency_candidates",
    "_repo_search_hints",
]
