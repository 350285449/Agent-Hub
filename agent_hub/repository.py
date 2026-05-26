from __future__ import annotations

import re
import subprocess
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .payloads import request_text
from .models import HubRequest


SKIP_DIRS = {".git", ".agent-hub", "__pycache__", "node_modules", ".venv", "dist", "build", ".pytest_cache"}
IMPORTANT_NAMES = {
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "setup.py",
    "tsconfig.json",
    "vite.config.ts",
    "webpack.config.js",
    "Dockerfile",
    "Makefile",
}
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".css": "css",
    ".html": "html",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
}


@dataclass(slots=True)
class FileInfo:
    path: str
    language: str = "text"
    size: int = 0
    important: bool = False
    changed: bool = False
    imports: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size": self.size,
            "important": self.important,
            "changed": self.changed,
            "imports": list(self.imports),
            "references": list(self.references),
        }


@dataclass(slots=True)
class RepositoryIndex:
    root: Path
    files: list[FileInfo] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    package_files: list[str] = field(default_factory=list)
    recently_changed_files: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    relationships: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": [file.to_dict() for file in self.files],
            "important_files": list(self.important_files),
            "package_files": list(self.package_files),
            "recently_changed_files": list(self.recently_changed_files),
            "languages": dict(self.languages),
            "relationships": self.relationships,
        }

    def has_file(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        return any(file.path == normalized for file in self.files)


@dataclass(slots=True)
class RepoContextSelection:
    files: list[FileInfo]
    summaries: dict[str, str]
    token_estimate: int
    truncated: bool
    warnings: list[str] = field(default_factory=list)

    def to_message(self) -> dict[str, Any] | None:
        if not self.files:
            return None
        lines = ["Repository evidence selected by Agent Hub:"]
        for file in self.files:
            summary = self.summaries.get(file.path, "")
            flags = []
            if file.important:
                flags.append("important")
            if file.changed:
                flags.append("changed")
            label = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"File: {file.path}{label}")
            if file.imports:
                lines.append("Imports: " + ", ".join(file.imports[:12]))
            if summary:
                lines.append(summary)
        if self.warnings:
            lines.append("Context warnings: " + "; ".join(self.warnings[:5]))
        return {
            "role": "system",
            "content": "\n\n".join(lines),
            "agent_hub_repo_context": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [file.to_dict() for file in self.files],
            "summaries": dict(self.summaries),
            "token_estimate": self.token_estimate,
            "truncated": self.truncated,
            "warnings": list(self.warnings),
        }


class RepositoryIndexer:
    def __init__(self, root: Path, *, ignore_patterns: list[str] | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.ignore_patterns = [pattern.replace("\\", "/") for pattern in (ignore_patterns or [])]

    def index(self, *, max_files: int = 2000) -> RepositoryIndex:
        changed = set(_git_changed_files(self.root))
        files: list[FileInfo] = []
        languages: dict[str, int] = {}
        for path in _iter_files(self.root, max_files=max_files, ignore_patterns=self.ignore_patterns):
            rel = path.relative_to(self.root).as_posix()
            language = _language(path)
            languages[language] = languages.get(language, 0) + 1
            important = _is_important(rel)
            text = _read_small_text(path)
            imports = _extract_imports(text, language)
            references = _extract_references(text)
            files.append(
                FileInfo(
                    path=rel,
                    language=language,
                    size=_safe_size(path),
                    important=important,
                    changed=rel in changed,
                    imports=imports,
                    references=references,
                )
            )
        important_files = [file.path for file in files if file.important]
        package_files = [file.path for file in files if Path(file.path).name in IMPORTANT_NAMES]
        recently_changed = [file.path for file in files if file.changed]
        relationships = {
            file.path: {"imports": list(file.imports), "references": list(file.references)}
            for file in files
            if file.imports or file.references
        }
        return RepositoryIndex(
            root=self.root,
            files=files,
            important_files=important_files,
            package_files=package_files,
            recently_changed_files=recently_changed,
            languages=languages,
            relationships=relationships,
        )


class RepoContextSelector:
    def __init__(self, index: RepositoryIndex) -> None:
        self.index = index

    def select(self, task: str, *, max_files: int = 8, max_chars: int = 12_000) -> RepoContextSelection:
        terms = set(_terms(task))
        scored: list[tuple[int, FileInfo]] = []
        for file in self.index.files:
            score = _score_file(file, terms)
            if score > 0:
                scored.append((score, file))
        if not scored:
            scored = [(2 if file.important else 1, file) for file in self.index.files if file.important or file.changed]
        selected: list[FileInfo] = []
        seen: set[str] = set()
        for _score, file in sorted(scored, key=lambda item: (-item[0], item[1].path)):
            if file.path in seen:
                continue
            seen.add(file.path)
            selected.append(file)
            if len(selected) >= max_files:
                break
        summaries: dict[str, str] = {}
        used = 0
        truncated = False
        for file in selected:
            path = self.index.root / file.path
            text = _read_small_text(path, limit=max_chars)
            remaining = max(0, max_chars - used)
            if remaining <= 0:
                truncated = True
                break
            summary = _summarize_file(text, maximum=min(remaining, 1600))
            used += len(summary)
            summaries[file.path] = summary
            if len(text) > len(summary):
                truncated = True
        warnings = _context_warnings(task, self.index, {file.path for file in selected})
        return RepoContextSelection(
            files=selected,
            summaries=summaries,
            token_estimate=max(1, used // 4),
            truncated=truncated,
            warnings=warnings,
        )


def repo_context_for_request(
    request: HubRequest,
    root: Path,
    *,
    max_files: int,
    max_chars: int,
    ignore_patterns: list[str] | None = None,
) -> RepoContextSelection:
    index = RepositoryIndexer(root, ignore_patterns=ignore_patterns).index()
    return RepoContextSelector(index).select(request_text(request), max_files=max_files, max_chars=max_chars)


def detect_uncontextualized_file_references(text: str, index: RepositoryIndex, selected_paths: set[str]) -> list[str]:
    warnings: list[str] = []
    for path in _referenced_paths(text):
        if not index.has_file(path):
            warnings.append(f"Referenced file is not in this repository: {path}")
        elif path not in selected_paths:
            warnings.append(f"Referenced file was not selected as evidence: {path}")
    return warnings[:20]


def _iter_files(root: Path, *, max_files: int, ignore_patterns: list[str] | None = None) -> list[Path]:
    files: list[Path] = []
    patterns = [pattern.replace("\\", "/") for pattern in (ignore_patterns or [])]
    for path in root.rglob("*"):
        if len(files) >= max_files:
            break
        rel = _relative_posix(root, path)
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if _matches_ignore(rel, patterns):
            continue
        if not path.is_file():
            continue
        if _safe_size(path) > 500_000:
            continue
        files.append(path)
    return files


def _matches_ignore(relative: str, patterns: list[str]) -> bool:
    normalized = relative.strip("./")
    for pattern in patterns:
        clean = pattern.strip().replace("\\", "/")
        if not clean:
            continue
        if fnmatch.fnmatch(normalized, clean) or fnmatch.fnmatch(normalized, clean.rstrip("/**")):
            return True
        if clean.endswith("/**") and normalized.startswith(clean[:-3].rstrip("/") + "/"):
            return True
    return False


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _git_changed_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        value = line[3:].strip()
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[1].strip()
        if value:
            paths.append(value.replace("\\", "/"))
    return paths


def _language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")


def _is_important(path: str) -> bool:
    name = Path(path).name
    return name in IMPORTANT_NAMES or path.startswith(("agent_hub/", "src/", "tests/", "docs/"))


def _read_small_text(path: Path, *, limit: int = 80_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _extract_imports(text: str, language: str) -> list[str]:
    imports: list[str] = []
    patterns = []
    if language == "python":
        patterns = [r"^\s*import\s+([a-zA-Z0-9_., ]+)", r"^\s*from\s+([a-zA-Z0-9_.]+)\s+import\b"]
    elif language in {"javascript", "typescript"}:
        patterns = [r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\brequire\(['\"]([^'\"]+)['\"]\)"]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            imports.append(match.group(1).strip())
    return _dedupe(imports)[:40]


def _extract_references(text: str) -> list[str]:
    return _dedupe(_referenced_paths(text))[:40]


def _referenced_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html)\b", text):
        value = match.group(0).strip("./").replace("\\", "/")
        if "/" in value or "." in value:
            paths.append(value)
    return paths


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9_./-]{3,}", str(text).lower())
        if word not in {"the", "and", "for", "with", "that", "this", "from"}
    ][:120]


def _score_file(file: FileInfo, terms: set[str]) -> int:
    haystack = f"{file.path} {file.language} {' '.join(file.imports)} {' '.join(file.references)}".lower()
    score = sum(3 if term in file.path.lower() else 1 for term in terms if term in haystack)
    if file.important:
        score += 2
    if file.changed:
        score += 5
    return score


def _summarize_file(text: str, *, maximum: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    selected = []
    for line in lines[:120]:
        if line.strip():
            selected.append(line[:240])
        if len("\n".join(selected)) >= maximum:
            break
    summary = "\n".join(selected)
    if len(summary) > maximum:
        return summary[: max(0, maximum - 16)].rstrip() + " [truncated]"
    return summary


def _context_warnings(task: str, index: RepositoryIndex, selected: set[str]) -> list[str]:
    return detect_uncontextualized_file_references(task, index, selected)


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
