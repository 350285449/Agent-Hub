from __future__ import annotations

import hashlib
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
    "build.gradle",
    "build.gradle.kts",
    "pom.xml",
    "Cargo.toml",
    "go.mod",
    "fabric.mod.json",
    "mods.toml",
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
    symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size": self.size,
            "important": self.important,
            "changed": self.changed,
            "imports": list(self.imports),
            "references": list(self.references),
            "symbols": list(self.symbols),
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
    levels: dict[str, str] = field(default_factory=dict)
    selected_files: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    reason: str = ""
    original_token_estimate: int = 0
    optimized_token_estimate: int = 0
    tokens_saved: int = 0
    saved_percent: float = 0.0
    cache_hits: int = 0
    total_files: int = 0

    def to_message(self) -> dict[str, Any] | None:
        if not self.files:
            return None
        lines = [
            "Agent Hub optimized this repository context.",
            (
                f"Files selected: {len(self.selected_files or self.files)}"
                + (f" of {self.total_files}" if self.total_files else "")
            ),
            f"Tokens saved: {self.saved_percent:.1f}%",
        ]
        if self.reason:
            lines.append("Reason: " + self.reason)
        for file in self.files:
            summary = self.summaries.get(file.path, "")
            level = self.levels.get(file.path, "Compressed")
            flags = []
            if file.important:
                flags.append("important")
            if file.changed:
                flags.append("changed")
            label = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"File: {file.path}{label}\nContext level: {level}")
            if file.imports:
                lines.append("Imports: " + ", ".join(file.imports[:12]))
            if file.symbols:
                lines.append("Symbols: " + ", ".join(file.symbols[:20]))
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
            "levels": dict(self.levels),
            "context_levels": dict(self.levels),
            "selected_files": list(self.selected_files or [file.path for file in self.files]),
            "excluded_files": list(self.excluded_files),
            "reason": self.reason,
            "original_context_tokens": self.original_token_estimate,
            "optimized_context_tokens": self.optimized_token_estimate or self.token_estimate,
            "tokens_saved": self.tokens_saved,
            "saved_percent": self.saved_percent,
            "cache_hits": self.cache_hits,
            "total_files": self.total_files,
        }


@dataclass(slots=True)
class FileRelevance:
    file: FileInfo
    score: float
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.file.path,
            "score": round(self.score, 3),
            "signals": list(self.signals),
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
            symbols = _extract_symbols(text, language)
            files.append(
                FileInfo(
                    path=rel,
                    language=language,
                    size=_safe_size(path),
                    important=important,
                    changed=rel in changed,
                    imports=imports,
                    references=references,
                    symbols=symbols,
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

    def rank_files(self, task: str, *, limit: int = 80) -> list[FileRelevance]:
        terms = set(_terms(task))
        mentioned = set(_referenced_paths(task))
        stack_paths = set(_stack_trace_paths(task))
        diff_paths = set(_git_diff_files(self.index.root))
        scored: list[FileRelevance] = []
        for file in self.index.files:
            if _is_generated_file(file.path):
                continue
            score, signals = _score_file(
                file,
                terms,
                mentioned_paths=mentioned,
                stack_paths=stack_paths,
                diff_paths=diff_paths,
            )
            if score > 0:
                scored.append(FileRelevance(file=file, score=score, signals=signals))
        if not scored:
            for file in self.index.files:
                if _is_generated_file(file.path):
                    continue
                if file.important or file.changed:
                    signals = ["important file"] if file.important else []
                    if file.changed:
                        signals.append("recent edit")
                    scored.append(FileRelevance(file=file, score=2.0 if file.important else 1.0, signals=signals))
        ranked = sorted(scored, key=lambda item: (-item.score, item.file.path))
        return ranked[: max(1, limit)]

    def select(
        self,
        task: str,
        *,
        max_files: int = 8,
        max_chars: int = 12_000,
        full_files: int = 2,
        compressed_files: int = 4,
        map_files: int = 6,
        compression_aggression: float = 0.55,
    ) -> RepoContextSelection:
        ranked = self.rank_files(task, limit=max(80, max_files * 6))
        selected_relevance = ranked[: max(1, max_files)]
        selected = [item.file for item in selected_relevance]
        levels = _assign_context_levels(
            selected,
            full_files=full_files,
            compressed_files=compressed_files,
            map_files=map_files,
        )
        summaries: dict[str, str] = {}
        used = 0
        original_chars = 0
        optimized_chars = 0
        truncated = False
        cache_hits = 0
        for item in selected_relevance:
            file = item.file
            path = self.index.root / file.path
            text = _read_small_text(path, limit=max(80_000, max_chars))
            original_chars += len(text)
            remaining = max(0, max_chars - used)
            if remaining <= 0:
                truncated = True
                break
            level = levels.get(file.path, "Compressed")
            body, cache_hit = _context_for_file(
                file,
                text,
                level=level,
                maximum=min(remaining, _level_char_budget(level, max_chars, compression_aggression)),
                compression_aggression=compression_aggression,
            )
            cache_hits += 1 if cache_hit else 0
            used += len(body)
            optimized_chars += len(body)
            summaries[file.path] = body
            if len(text) > len(body) and level != "Full":
                truncated = True
        selected_paths = [file.path for file in selected]
        excluded = [item.file.path for item in ranked[max_files : max_files + 40]]
        warnings = _context_warnings(task, self.index, set(selected_paths))
        original_tokens = max(1, original_chars // 4)
        optimized_tokens = max(1, optimized_chars // 4)
        tokens_saved = max(0, original_tokens - optimized_tokens)
        reason = _selection_reason(selected_relevance)
        return RepoContextSelection(
            files=selected,
            summaries=summaries,
            token_estimate=optimized_tokens,
            truncated=truncated,
            warnings=warnings,
            levels=levels,
            selected_files=selected_paths,
            excluded_files=excluded,
            reason=reason,
            original_token_estimate=original_tokens,
            optimized_token_estimate=optimized_tokens,
            tokens_saved=tokens_saved,
            saved_percent=round((tokens_saved / max(1, original_tokens)) * 100, 1),
            cache_hits=cache_hits,
            total_files=len([file for file in self.index.files if not _is_generated_file(file.path)]),
        )


def repo_context_for_request(
    request: HubRequest,
    root: Path,
    *,
    max_files: int,
    max_chars: int,
    ignore_patterns: list[str] | None = None,
    full_files: int = 2,
    compressed_files: int = 4,
    map_files: int = 6,
    compression_aggression: float = 0.55,
) -> RepoContextSelection:
    index = RepositoryIndexer(root, ignore_patterns=ignore_patterns).index()
    return RepoContextSelector(index).select(
        request_text(request),
        max_files=max_files,
        max_chars=max_chars,
        full_files=full_files,
        compressed_files=compressed_files,
        map_files=map_files,
        compression_aggression=compression_aggression,
    )


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


def _extract_symbols(text: str, language: str) -> list[str]:
    patterns: list[str] = []
    if language == "python":
        patterns = [
            r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^([A-Z][A-Z0-9_]{2,})\s*=",
        ]
    elif language in {"javascript", "typescript"}:
        patterns = [
            r"\b(?:function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=",
            r"\bexport\s+(?:default\s+)?(?:function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        ]
    elif language in {"go", "rust", "java", "csharp"}:
        patterns = [
            r"\b(?:func|fn|class|interface|enum|struct)\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]
    symbols: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            symbols.append(match.group(1))
    return _dedupe(symbols)[:80]


def _referenced_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html|go|rs|java|cs)\b", text):
        value = match.group(0).strip("./").replace("\\", "/")
        if "/" in value or "." in value:
            paths.append(value)
    return paths


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9_./-]{3,}", str(text).lower())
        if word not in {"the", "and", "for", "with", "that", "this", "from", "into", "your", "agent", "hub"}
    ][:120]


def _score_file(
    file: FileInfo,
    terms: set[str],
    *,
    mentioned_paths: set[str],
    stack_paths: set[str],
    diff_paths: set[str],
) -> tuple[float, list[str]]:
    haystack = (
        f"{file.path} {file.language} {' '.join(file.imports)} "
        f"{' '.join(file.references)} {' '.join(file.symbols)}"
    ).lower()
    path_lower = file.path.lower()
    basename = Path(file.path).name.lower()
    score = 0.0
    signals: list[str] = []
    if file.path in mentioned_paths or basename in {Path(path).name.lower() for path in mentioned_paths}:
        score += 80.0
        signals.append("file mentioned in prompt")
    if file.path in stack_paths or basename in {Path(path).name.lower() for path in stack_paths}:
        score += 70.0
        signals.append("matched error stack trace")
    if file.changed:
        score += 30.0
        signals.append("recent edit")
    if file.path in diff_paths:
        score += 28.0
        signals.append("git diff relevance")
    path_hits = [term for term in terms if term in path_lower]
    if path_hits:
        score += min(30.0, len(path_hits) * 6.0)
        signals.append("path terms matched")
    symbol_hits = [term for term in terms if any(term in symbol.lower() for symbol in file.symbols)]
    if symbol_hits:
        score += min(24.0, len(symbol_hits) * 8.0)
        signals.append("symbol matches")
    dependency_hits = [term for term in terms if term in haystack and term not in path_lower]
    if dependency_hits:
        score += min(18.0, len(dependency_hits) * 3.0)
        signals.append("imports/dependencies matched")
    folders = {str(Path(path).parent).replace("\\", "/") for path in mentioned_paths if "/" in path}
    if folders and str(Path(file.path).parent).replace("\\", "/") in folders:
        score += 10.0
        signals.append("same folder as referenced file")
    if _looks_like_test_file(file.path) and terms & {"test", "tests", "pytest", "failing", "failure", "bug"}:
        score += 12.0
        signals.append("test file")
    if file.important:
        score += 4.0
        signals.append("important project file")
    return score, _dedupe(signals)


_SUMMARY_CACHE: dict[str, str] = {}


def _assign_context_levels(
    files: list[FileInfo],
    *,
    full_files: int,
    compressed_files: int,
    map_files: int,
) -> dict[str, str]:
    levels: dict[str, str] = {}
    full_limit = max(0, full_files)
    compressed_limit = full_limit + max(0, compressed_files)
    map_limit = compressed_limit + max(0, map_files)
    for index, file in enumerate(files):
        if index < full_limit and file.size <= 80_000:
            levels[file.path] = "Full"
        elif index < compressed_limit:
            levels[file.path] = "Compressed"
        elif index < map_limit:
            levels[file.path] = "Map"
        else:
            levels[file.path] = "Omitted"
    return levels


def _context_for_file(
    file: FileInfo,
    text: str,
    *,
    level: str,
    maximum: int,
    compression_aggression: float,
) -> tuple[str, bool]:
    if maximum <= 0 or level == "Omitted":
        return "", False
    if level == "Full":
        body = text[:maximum]
        if len(text) > len(body):
            body = body.rstrip() + "\n[File truncated to fit optimized context]"
        return _format_context_block(file, level, body), False
    cache_key = _summary_cache_key(file, text, level=level, maximum=maximum, compression_aggression=compression_aggression)
    cached = _SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached, True
    if level == "Map":
        body = _file_map(file, maximum=maximum)
    else:
        body = _compressed_file_summary(
            file,
            text,
            maximum=maximum,
            compression_aggression=compression_aggression,
        )
    _SUMMARY_CACHE[cache_key] = body
    if len(_SUMMARY_CACHE) > 512:
        for key in list(_SUMMARY_CACHE)[:128]:
            _SUMMARY_CACHE.pop(key, None)
    return body, False


def _compressed_file_summary(
    file: FileInfo,
    text: str,
    *,
    maximum: int,
    compression_aggression: float,
) -> str:
    stripped = _strip_comments(text, file.language) if compression_aggression >= 0.45 else text
    stripped = _dedupe_repeated_lines(stripped)
    snippets = _key_snippets(stripped, file.language)
    intro = [
        f"Summary for {file.path}:",
        f"Language: {file.language}. Size: {file.size} bytes.",
    ]
    if file.imports:
        intro.append("Imports: " + ", ".join(file.imports[:12]))
    if file.symbols:
        intro.append("Key symbols: " + ", ".join(file.symbols[:24]))
    content = "\n".join([*intro, "", *snippets])
    if len(content) < min(maximum, 600):
        content = "\n".join([content, "", _summarize_file(stripped, maximum=max(0, maximum - len(content) - 2))])
    return _fit(content, maximum)


def _file_map(file: FileInfo, *, maximum: int) -> str:
    parts = [
        f"Map for {file.path}:",
        f"Language: {file.language}. Size: {file.size} bytes.",
    ]
    if file.imports:
        parts.append("Imports: " + ", ".join(file.imports[:30]))
    if file.symbols:
        parts.append("Symbols: " + ", ".join(file.symbols[:50]))
    if file.references:
        parts.append("References: " + ", ".join(file.references[:20]))
    return _fit("\n".join(parts), maximum)


def _format_context_block(file: FileInfo, level: str, body: str) -> str:
    if level == "Full":
        return f"Full text for {file.path}:\n```{file.language}\n{body}\n```"
    return body


def _summarize_file(text: str, *, maximum: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    selected = []
    for line in lines[:160]:
        if line.strip():
            selected.append(line[:240])
        if len("\n".join(selected)) >= maximum:
            break
    return _fit("\n".join(selected), maximum)


def _key_snippets(text: str, language: str) -> list[str]:
    lines = text.splitlines()
    selected: list[str] = []
    patterns = [
        r"^\s*(?:async\s+def|def|class)\s+",
        r"^\s*(?:export\s+)?(?:function|class|const|let)\s+",
        r"^\s*(?:func|fn|pub\s+fn|struct|interface|enum)\s+",
    ]
    for index, line in enumerate(lines):
        if not any(re.search(pattern, line) for pattern in patterns):
            continue
        block = [line.rstrip()]
        for follow in lines[index + 1 : index + 8]:
            if follow.strip():
                block.append(follow.rstrip()[:220])
        selected.append("\n".join(block))
        if len(selected) >= 8:
            break
    if selected:
        return selected
    fallback = []
    for line in lines[:80]:
        if line.strip():
            fallback.append(line.rstrip()[:220])
        if len(fallback) >= 20:
            break
    return fallback


def _strip_comments(text: str, language: str) -> str:
    if language == "python":
        lines = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("#")
        ]
        return "\n".join(lines)
    if language in {"javascript", "typescript", "java", "go", "rust", "csharp"}:
        lines = [
            re.sub(r"\s*//.*$", "", line)
            for line in text.splitlines()
            if not line.lstrip().startswith("//")
        ]
        return "\n".join(lines)
    return text


def _dedupe_repeated_lines(text: str) -> str:
    result: list[str] = []
    previous = ""
    repeat_count = 0
    for line in text.splitlines():
        normalized = line.strip()
        if normalized and normalized == previous:
            repeat_count += 1
            if repeat_count > 2:
                continue
        else:
            repeat_count = 0
        previous = normalized
        result.append(line)
    return "\n".join(result)


def _fit(text: str, maximum: int) -> str:
    if maximum <= 0:
        return ""
    if len(text) <= maximum:
        return text
    return text[: max(0, maximum - 16)].rstrip() + " [truncated]"


def _level_char_budget(level: str, max_chars: int, compression_aggression: float) -> int:
    if level == "Full":
        return max(800, min(8_000, int(max_chars * 0.45)))
    if level == "Map":
        return max(240, min(1_200, int(max_chars * 0.08)))
    base = 0.22 - min(0.16, max(0.0, compression_aggression) * 0.12)
    return max(600, min(2_400, int(max_chars * base)))


def _summary_cache_key(
    file: FileInfo,
    text: str,
    *,
    level: str,
    maximum: int,
    compression_aggression: float,
) -> str:
    digest = hashlib.sha256(text[:120_000].encode("utf-8", errors="replace")).hexdigest()[:20]
    return f"{file.path}:{file.size}:{level}:{maximum}:{compression_aggression:.2f}:{digest}"


def _selection_reason(items: list[FileRelevance]) -> str:
    signals: list[str] = []
    for item in items[:8]:
        signals.extend(item.signals)
    if not signals:
        return "Selected important or recently changed repository files."
    return "Matched " + ", ".join(_dedupe(signals)[:6]) + "."


def _stack_trace_paths(text: str) -> list[str]:
    paths: list[str] = []
    patterns = [
        r'File "([^"]+\.(?:py|js|ts|tsx|jsx|java|go|rs))", line \d+',
        r"\bat\s+[\w.$<>]+\(([^():]+\.(?:java|js|ts|tsx):\d+)\)",
        r"([A-Za-z0-9_./-]+\.(?:py|js|ts|tsx|jsx|java|go|rs)):\d+",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).split(":", 1)[0].strip().replace("\\", "/").strip("./")
            if value and value not in paths:
                paths.append(value)
    return paths[:40]


def _git_diff_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    return _dedupe([line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()])


def _is_generated_file(path: str) -> bool:
    lowered = path.lower()
    name = Path(path).name.lower()
    if any(part in lowered.split("/") for part in {"dist", "build", "coverage", "node_modules", ".venv"}):
        return True
    if name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "cargo.lock"}:
        return True
    return any(
        marker in lowered
        for marker in (
            ".generated.",
            ".min.js",
            ".bundle.",
            "__generated__",
            "generated/",
        )
    )


def _looks_like_test_file(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith("tests/") or "/tests/" in lowered or Path(lowered).name.startswith("test_") or "_test." in lowered


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
