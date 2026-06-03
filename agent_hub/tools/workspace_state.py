from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .workspace_safety import MAX_CHECKPOINT_RETENTION, ToolError, _positive_int


def create_workspace_checkpoint(
    root: str | Path,
    paths: list[str | Path],
    *,
    state_dir: str | Path | None = None,
    retention: int = 5,
    reason: str = "",
) -> dict[str, Any]:
    """Persist a small pre-edit snapshot for files inside the workspace."""

    workspace = Path(root).expanduser().resolve()
    unique_paths = _unique_checkpoint_paths(workspace, paths)
    if not unique_paths:
        raise ToolError("Cannot create a checkpoint without workspace paths")

    checkpoints_dir = _checkpoint_base_dir(workspace, state_dir)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{checkpoint_id}.", dir=checkpoints_dir))
    files_dir = temp_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "id": checkpoint_id,
        "created_at": time.time(),
        "root": str(workspace),
        "reason": reason,
        "files": [],
    }
    try:
        for path in unique_paths:
            relative = _relative_to_workspace(workspace, path)
            entry: dict[str, Any] = {"path": relative, "exists": path.exists()}
            if path.exists():
                if not path.is_file():
                    raise ToolError(f"Cannot checkpoint non-file path: {relative}")
                snapshot_name = f"{len(manifest['files']):04d}.bin"
                shutil.copy2(path, files_dir / snapshot_name)
                entry["snapshot"] = f"files/{snapshot_name}"
                entry["size"] = path.stat().st_size
            manifest["files"].append(entry)

        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        checkpoint_dir = checkpoints_dir / checkpoint_id
        temp_dir.rename(checkpoint_dir)
        _prune_workspace_checkpoints(checkpoints_dir, retention)
        return _checkpoint_public_manifest(manifest, checkpoint_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def restore_workspace_checkpoint(
    checkpoint: dict[str, Any] | str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Restore files captured by create_workspace_checkpoint."""

    manifest, checkpoint_dir = _load_checkpoint_manifest(checkpoint)
    workspace = Path(root or manifest.get("root") or ".").expanduser().resolve()
    restored: list[str] = []
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            continue
        relative = str(entry.get("path") or "")
        try:
            target = _canonical_workspace_path(workspace, relative, allow_missing=True)
            if entry.get("exists"):
                snapshot = entry.get("snapshot")
                if not isinstance(snapshot, str) or not snapshot:
                    raise ToolError(f"Checkpoint entry for {relative} is missing a snapshot")
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy_file(checkpoint_dir / snapshot, target)
                restored.append(relative)
            else:
                if target.exists():
                    if not target.is_file():
                        raise ToolError(f"Refusing to remove non-file path during restore: {relative}")
                    target.unlink()
                    removed.append(relative)
        except Exception as exc:
            errors.append({"path": relative, "error": str(exc)})
    return {
        "ok": not errors,
        "checkpoint_id": str(manifest.get("id") or ""),
        "restored_files": restored,
        "removed_files": removed,
        "errors": errors,
    }


def _checkpoint_base_dir(root: Path, state_dir: str | Path | None) -> Path:
    if state_dir is None:
        base = root / ".agent-hub" / "state"
    else:
        base = Path(state_dir).expanduser()
        if not base.is_absolute():
            base = root / base
    return base.resolve() / "workspace-checkpoints"


def _unique_checkpoint_paths(root: Path, paths: list[str | Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for value in paths:
        path = _canonical_workspace_path(root, value, allow_missing=True)
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _canonical_workspace_path(
    root: Path,
    value: str | Path,
    *,
    allow_missing: bool,
) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve()
    except OSError:
        if not allow_missing:
            raise
        resolved = candidate.parent.resolve() / candidate.name
    if resolved != root and not resolved.is_relative_to(root):
        raise ToolError(f"Path escapes workspace: {value}")
    return resolved


def _relative_to_workspace(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        raise ToolError(f"Path escapes workspace: {path}") from None


def _workspace_relative_config_path(root: Path, value: Any) -> Path | None:
    if value is None:
        return None
    try:
        path = Path(value).expanduser()
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    except (OSError, TypeError, ValueError):
        return None
    return resolved if resolved == root or resolved.is_relative_to(root) else None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _checkpoint_public_manifest(manifest: dict[str, Any], checkpoint_dir: Path) -> dict[str, Any]:
    files = manifest.get("files", [])
    paths = [
        str(entry.get("path"))
        for entry in files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    return {
        "id": str(manifest.get("id") or ""),
        "created_at": manifest.get("created_at"),
        "root": str(manifest.get("root") or ""),
        "reason": str(manifest.get("reason") or ""),
        "paths": paths,
        "checkpoint_dir": str(checkpoint_dir),
    }


def _load_checkpoint_manifest(
    checkpoint: dict[str, Any] | str | Path,
) -> tuple[dict[str, Any], Path]:
    if isinstance(checkpoint, dict):
        checkpoint_dir_value = checkpoint.get("checkpoint_dir") or checkpoint.get("path")
        if not isinstance(checkpoint_dir_value, str) or not checkpoint_dir_value:
            raise ToolError("Checkpoint metadata is missing checkpoint_dir")
        checkpoint_dir = Path(checkpoint_dir_value).expanduser().resolve()
    else:
        checkpoint_dir = Path(checkpoint).expanduser().resolve()
    manifest_path = checkpoint_dir / "manifest.json"
    if not manifest_path.exists():
        raise ToolError(f"Checkpoint manifest does not exist: {checkpoint_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), checkpoint_dir


def _prune_workspace_checkpoints(checkpoints_dir: Path, retention: int) -> None:
    keep = _positive_int(retention, default=5, maximum=MAX_CHECKPOINT_RETENTION)
    manifests: list[tuple[float, Path]] = []
    for child in checkpoints_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created_at = float(manifest.get("created_at", 0.0))
        except Exception:
            created_at = child.stat().st_mtime
        manifests.append((created_at, child))
    for _, child in sorted(manifests, reverse=True)[keep:]:
        shutil.rmtree(child, ignore_errors=True)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass




__all__ = [
    "create_workspace_checkpoint",
    "restore_workspace_checkpoint",
    "_checkpoint_base_dir",
    "_unique_checkpoint_paths",
    "_canonical_workspace_path",
    "_relative_to_workspace",
    "_workspace_relative_config_path",
    "_dedupe_paths",
    "_checkpoint_public_manifest",
    "_load_checkpoint_manifest",
    "_prune_workspace_checkpoints",
    "_atomic_write_text",
    "_atomic_copy_file",
]
