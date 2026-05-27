from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_MANIFEST_NAME = "SNAPSHOT.json"
SNAPSHOT_EXTRAS = ("pyproject.toml", "README.md", "release.json")
REQUIRED_SNAPSHOT_FILES = (
    "agent_hub/__init__.py",
    "agent_hub/__main__.py",
    "agent_hub/version.py",
    "pyproject.toml",
    "release.json",
)
EXCLUDED_NAMES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".DS_Store",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp", ".log"}
FORBIDDEN_SNAPSHOT_NAMES = {name.lower() for name in EXCLUDED_NAMES} | {
    ".env",
    ".git",
    ".vscode",
    ".vscode-test",
    "node_modules",
    "tests",
}
FORBIDDEN_SNAPSHOT_SUFFIXES = EXCLUDED_SUFFIXES | {
    ".bak",
    ".backup",
    ".swp",
    ".vsix",
}


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    source: Path
    relative_path: str
    sha256: str
    size: int

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "size": self.size,
        }


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def generate_snapshot(root: Path | None = None) -> dict[str, Any]:
    root = (root or repo_root_from_script()).resolve()
    backend_root = snapshot_root(root)
    _assert_snapshot_target(root, backend_root)
    if backend_root.exists():
        shutil.rmtree(backend_root)
    backend_root.mkdir(parents=True, exist_ok=True)

    files = source_files(root)
    for item in files:
        destination = backend_root / item.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source, destination)

    manifest = build_manifest(root, files=files)
    write_manifest(backend_root / SNAPSHOT_MANIFEST_NAME, manifest)
    return manifest


def validate_snapshot(root: Path | None = None) -> list[str]:
    root = (root or repo_root_from_script()).resolve()
    backend_root = snapshot_root(root)
    failures: list[str] = []
    if not backend_root.exists():
        return [f"backend snapshot is missing: {_rel(root, backend_root)}"]
    forbidden = forbidden_snapshot_files(backend_root)
    for path in forbidden[:20]:
        failures.append(f"forbidden snapshot file: {_posix(path.relative_to(backend_root))}")
    if len(forbidden) > 20:
        failures.append(f"{len(forbidden) - 20} more forbidden snapshot files exist")

    expected_files = source_files(root)
    expected_manifest = build_manifest(root, files=expected_files)
    manifest_path = backend_root / SNAPSHOT_MANIFEST_NAME
    if not manifest_path.exists():
        failures.append(f"snapshot manifest is missing: {_rel(root, manifest_path)}")
    else:
        try:
            actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"snapshot manifest is invalid JSON: {exc.msg}")
            actual_manifest = {}
        if actual_manifest and actual_manifest != expected_manifest:
            failures.append("snapshot manifest checksum differs from canonical source")

    expected_paths = {item.relative_path for item in expected_files}
    for required in REQUIRED_SNAPSHOT_FILES:
        if required not in expected_paths:
            failures.append(f"required canonical file missing: {required}")
    actual_paths = {
        _posix(path.relative_to(backend_root))
        for path in backend_root.rglob("*")
        if path.is_file() and path.name != SNAPSHOT_MANIFEST_NAME and _included(path)
    }
    for required in REQUIRED_SNAPSHOT_FILES:
        if required not in actual_paths:
            failures.append(f"required snapshot file missing: {required}")
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    for path in missing[:20]:
        failures.append(f"snapshot file missing: {path}")
    for path in unexpected[:20]:
        failures.append(f"unexpected snapshot file: {path}")
    if len(missing) > 20:
        failures.append(f"{len(missing) - 20} more snapshot files are missing")
    if len(unexpected) > 20:
        failures.append(f"{len(unexpected) - 20} more unexpected snapshot files exist")

    for item in expected_files:
        destination = backend_root / item.relative_path
        if not destination.exists():
            continue
        actual_hash = file_sha256(destination)
        if actual_hash != item.sha256:
            failures.append(f"snapshot file drift: {item.relative_path}")
    return failures


def source_files(root: Path) -> list[SnapshotFile]:
    files: list[SnapshotFile] = []
    package_root = root / "agent_hub"
    for path in sorted(package_root.rglob("*"), key=lambda item: _posix(item.relative_to(root))):
        if path.is_file() and _included(path):
            files.append(snapshot_file(path, _posix(path.relative_to(root))))
    for name in SNAPSHOT_EXTRAS:
        path = root / name
        if path.exists() and path.is_file() and _included(path):
            files.append(snapshot_file(path, name))
    return files


def snapshot_file(path: Path, relative_path: str) -> SnapshotFile:
    return SnapshotFile(
        source=path,
        relative_path=relative_path,
        sha256=file_sha256(path),
        size=path.stat().st_size,
    )


def build_manifest(root: Path, *, files: list[SnapshotFile] | None = None) -> dict[str, Any]:
    files = files if files is not None else source_files(root)
    entries = [item.to_manifest_entry() for item in files]
    tree_hash = hashlib.sha256()
    for item in entries:
        tree_hash.update(item["path"].encode("utf-8"))
        tree_hash.update(b"\0")
        tree_hash.update(item["sha256"].encode("ascii"))
        tree_hash.update(b"\0")
        tree_hash.update(str(item["size"]).encode("ascii"))
        tree_hash.update(b"\n")
    release = read_json(root / "release.json")
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_by": "scripts/generate_backend_snapshot.py",
        "canonical_source": "agent_hub",
        "snapshot_root": "vscode-extension/backend",
        "release_manifest": "release.json" if (root / "release.json").exists() else "",
        "extension_version": release.get("extension_version", ""),
        "backend_version": release.get("backend_version", ""),
        "file_count": len(entries),
        "tree_sha256": tree_hash.hexdigest(),
        "files": entries,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def forbidden_snapshot_files(backend_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in backend_root.rglob("*"):
        if path.is_file() and path.name != SNAPSHOT_MANIFEST_NAME and _forbidden_snapshot_file(path):
            files.append(path)
    return sorted(files, key=lambda item: _posix(item.relative_to(backend_root)))


def snapshot_root(root: Path) -> Path:
    return root / "vscode-extension" / "backend"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _included(path: Path) -> bool:
    return not (
        any(part in EXCLUDED_NAMES for part in path.parts)
        or path.suffix.lower() in EXCLUDED_SUFFIXES
    )


def _forbidden_snapshot_file(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        any(part in FORBIDDEN_SNAPSHOT_NAMES for part in lower_parts)
        or name.startswith(".env.")
        or name.endswith(".config.local.json")
        or name.endswith(".config.backup.json")
        or path.suffix.lower() in FORBIDDEN_SNAPSHOT_SUFFIXES
    )


def _assert_snapshot_target(root: Path, backend_root: Path) -> None:
    expected = (root / "vscode-extension" / "backend").resolve()
    actual = backend_root.resolve()
    if actual != expected:
        raise ValueError(f"Refusing to rewrite unexpected backend snapshot path: {actual}")
    try:
        actual.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Refusing to rewrite snapshot outside repo root: {actual}") from exc


def _posix(path: Path) -> str:
    return path.as_posix()


def _rel(root: Path, path: Path) -> str:
    try:
        return _posix(path.relative_to(root))
    except ValueError:
        return str(path)
