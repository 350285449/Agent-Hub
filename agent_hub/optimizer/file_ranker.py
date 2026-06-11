from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RankedFile:
    file: Any
    score: float
    signals: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return str(getattr(self.file, "path", "")).replace("\\", "/")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "score": round(self.score, 3),
            "signals": list(self.signals),
        }


class FileRanker:
    def __init__(self, index: Any) -> None:
        self.index = index

    def rank_files(self, task: str, *, limit: int = 80) -> list[RankedFile]:
        terms = set(_terms(task))
        mentioned = set(_referenced_paths(task))
        stack_paths = set(_stack_trace_paths(task))
        diff_paths = set(_git_diff_files(getattr(self.index, "root", Path.cwd())))
        scored: list[RankedFile] = []
        for file in getattr(self.index, "files", []) or []:
            path = str(getattr(file, "path", "")).replace("\\", "/")
            if not path or _is_generated_file(path):
                continue
            score, signals = _score_file(
                file,
                terms,
                mentioned_paths=mentioned,
                stack_paths=stack_paths,
                diff_paths=diff_paths,
            )
            if score > 0:
                scored.append(RankedFile(file=file, score=score, signals=signals))
        if not scored:
            for file in getattr(self.index, "files", []) or []:
                path = str(getattr(file, "path", "")).replace("\\", "/")
                if not path or _is_generated_file(path):
                    continue
                signals = ["important file"] if bool(getattr(file, "important", False)) else []
                if bool(getattr(file, "changed", False)):
                    signals.append("recent edit")
                if signals:
                    scored.append(
                        RankedFile(
                            file=file,
                            score=2.0 if bool(getattr(file, "important", False)) else 1.0,
                            signals=signals,
                        )
                    )
        ranked = sorted(scored, key=lambda item: (-item.score, item.path))
        return ranked[: max(1, limit)]

    def select_diverse(
        self,
        ranked: list[RankedFile],
        *,
        max_files: int,
        task: str,
    ) -> list[RankedFile]:
        return _select_diverse_relevance(ranked, max_files=max_files, task=task)

    def total_rankable_files(self) -> int:
        return len(
            [
                file
                for file in getattr(self.index, "files", []) or []
                if not _is_generated_file(str(getattr(file, "path", "")).replace("\\", "/"))
            ]
        )


def _score_file(
    file: Any,
    terms: set[str],
    *,
    mentioned_paths: set[str],
    stack_paths: set[str],
    diff_paths: set[str],
) -> tuple[float, list[str]]:
    path = str(getattr(file, "path", "")).replace("\\", "/")
    imports = [str(value) for value in getattr(file, "imports", []) or []]
    references = [str(value) for value in getattr(file, "references", []) or []]
    symbols = [str(value) for value in getattr(file, "symbols", []) or []]
    haystack = (
        f"{path} {getattr(file, 'language', 'text')} {' '.join(imports)} "
        f"{' '.join(references)} {' '.join(symbols)}"
    ).lower()
    path_lower = path.lower()
    basename = Path(path).name.lower()
    score = 0.0
    signals: list[str] = []
    mentioned_names = {Path(item).name.lower() for item in mentioned_paths}
    stack_names = {Path(item).name.lower() for item in stack_paths}
    if path in mentioned_paths or basename in mentioned_names:
        score += 80.0
        signals.append("file mentioned in prompt")
    if path in stack_paths or basename in stack_names:
        score += 70.0
        signals.append("matched error stack trace")
    if bool(getattr(file, "changed", False)):
        score += 30.0
        signals.append("recent edit")
    if path in diff_paths:
        score += 28.0
        signals.append("git diff relevance")
    path_hits = [term for term in terms if term in path_lower]
    if path_hits:
        score += min(30.0, len(path_hits) * 6.0)
        signals.append("path terms matched")
    symbol_hits = [term for term in terms if any(term in symbol.lower() for symbol in symbols)]
    if symbol_hits:
        score += min(24.0, len(symbol_hits) * 8.0)
        signals.append("symbol matches")
    dependency_hits = [term for term in terms if term in haystack and term not in path_lower]
    if dependency_hits:
        score += min(18.0, len(dependency_hits) * 3.0)
        signals.append("imports/dependencies matched")
    folders = {str(Path(item).parent).replace("\\", "/") for item in mentioned_paths if "/" in item}
    if folders and str(Path(path).parent).replace("\\", "/") in folders:
        score += 10.0
        signals.append("same folder as referenced file")
    if _looks_like_test_file(path) and terms & {"test", "tests", "pytest", "failing", "failure", "bug"}:
        score += 12.0
        signals.append("test file")
    if bool(getattr(file, "important", False)):
        score += 4.0
        signals.append("important project file")
    return score, _dedupe(signals)


def _select_diverse_relevance(
    ranked: list[RankedFile],
    *,
    max_files: int,
    task: str,
) -> list[RankedFile]:
    if len(ranked) <= max_files:
        return list(ranked)
    selected = [ranked[0]]
    remaining = list(ranked[1:])
    terms = set(_terms(task))
    while remaining and len(selected) < max_files:
        best = max(
            remaining,
            key=lambda item: _diverse_relevance_score(item, selected, terms=terms),
        )
        selected.append(best)
        remaining.remove(best)
    return selected


def _diverse_relevance_score(
    item: RankedFile,
    selected: list[RankedFile],
    *,
    terms: set[str],
) -> float:
    selected_paths = {entry.path for entry in selected}
    selected_dirs = {str(Path(entry.path).parent).replace("\\", "/") for entry in selected}
    selected_languages = {str(getattr(entry.file, "language", "text")) for entry in selected}
    directory = str(Path(item.path).parent).replace("\\", "/")
    score = item.score
    if directory not in selected_dirs:
        score += 4.0
    elif len(selected_dirs) > 1:
        score -= 2.0
    if str(getattr(item.file, "language", "text")) not in selected_languages:
        score += 3.0
    if _looks_like_test_file(item.path) and any(not _looks_like_test_file(entry.path) for entry in selected):
        score += 8.0
    if not _looks_like_test_file(item.path) and any(_looks_like_test_file(entry.path) for entry in selected):
        score += 3.0
    score += _source_test_pair_bonus(item.path, selected_paths)
    if bool(getattr(item.file, "important", False)) and terms & {"config", "dependency", "build", "install", "package"}:
        score += 5.0
    if bool(getattr(item.file, "changed", False)):
        score += 4.0
    return score


def _source_test_pair_bonus(path: str, selected_paths: set[str]) -> float:
    stem = _normalized_file_stem(path)
    if not stem:
        return 0.0
    for selected in selected_paths:
        other = _normalized_file_stem(selected)
        if not other or other != stem:
            continue
        if _looks_like_test_file(path) != _looks_like_test_file(selected):
            return 18.0
    return 0.0


def _normalized_file_stem(path: str) -> str:
    stem = Path(path).stem.lower()
    for prefix in ("test_", "spec_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    for suffix in ("_test", ".test", "_spec", ".spec"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9_./-]{3,}", str(text).lower())
        if word not in {"the", "and", "for", "with", "that", "this", "from", "into", "your", "agent", "hub"}
    ][:120]


def _referenced_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|toml|yml|yaml|css|html|go|rs|java|cs)\b", text):
        value = match.group(0).strip("./").replace("\\", "/")
        if "/" in value or "." in value:
            paths.append(value)
    return _dedupe(paths)


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


def _git_diff_files(root: str | Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=Path(root),
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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

