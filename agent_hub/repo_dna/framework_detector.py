from __future__ import annotations

from pathlib import Path

from .dependency_detector import read_package_dependencies


def detect_language(root: str | Path) -> str:
    root = Path(root)
    files = list(_iter_repo_files(root))
    counts = {
        "Python": sum(1 for path in files if path.suffix == ".py"),
        "TypeScript": sum(1 for path in files if path.suffix in {".ts", ".tsx"}),
        "JavaScript": sum(1 for path in files if path.suffix in {".js", ".jsx"}),
        "Go": sum(1 for path in files if path.suffix == ".go"),
        "Rust": sum(1 for path in files if path.suffix == ".rs"),
        "Java": sum(1 for path in files if path.suffix == ".java"),
    }
    language, count = max(counts.items(), key=lambda item: item[1])
    return language if count else "unknown"


def detect_framework(root: str | Path) -> str:
    deps = " ".join(sorted(read_package_dependencies(root)))
    checks = [
        ("FastAPI", ("fastapi",)),
        ("Django", ("django",)),
        ("Flask", ("flask",)),
        ("Typer", ("typer",)),
        ("SQLAlchemy", ("sqlalchemy",)),
        ("React", ("react",)),
        ("Next.js", ("next",)),
        ("Vue", ("vue",)),
        ("Svelte", ("svelte",)),
        ("Express", ("express",)),
        ("Pydantic", ("pydantic",)),
    ]
    found = [label for label, terms in checks if any(term in deps for term in terms)]
    return ", ".join(found[:4]) if found else "unknown"


def _iter_repo_files(root: Path):
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
    for path in root.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            yield path
