from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


TEMP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".vscode-test"}
TEMP_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp", ".log"}


def package_artifacts(
    root: Path,
    *,
    include_vsix: bool = True,
    include_current_vsix: bool = False,
) -> list[Path]:
    extension = root / "vscode-extension"
    current_vsix = _current_vsix_path(root)
    paths: list[Path] = []
    seen: set[Path] = set()
    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(path)

    for path in extension.rglob("*"):
        if any(part == "node_modules" for part in path.parts):
            continue
        if path.is_dir() and path.name in TEMP_DIR_NAMES:
            add(path)
            continue
        if path.is_file() and (path.suffix.lower() in TEMP_SUFFIXES or path.name.endswith("~")):
            add(path)
            continue
        if include_vsix and path.is_file() and path.suffix.lower() == ".vsix":
            if not include_current_vsix and current_vsix and path.resolve() == current_vsix:
                continue
            add(path)
    if include_vsix:
        for path in root.rglob("*.vsix"):
            if any(part in {"node_modules", ".git"} for part in path.parts):
                continue
            if not include_current_vsix and current_vsix and path.resolve() == current_vsix:
                continue
            add(path)
    return sorted(paths, key=lambda item: item.as_posix())


def clean(paths: list[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def cleanup_messages(root: Path, paths: list[Path], *, apply: bool) -> list[str]:
    if not paths:
        return ["No package cleanup artifacts found."]
    action = "Removing" if apply else "Would remove"
    messages = [f"{action}: {path.relative_to(root)}" for path in paths]
    if not apply:
        messages.append("Dry run only. Add --apply to delete these artifacts.")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean package-only temporary artifacts.")
    parser.add_argument("--apply", action="store_true", help="Delete discovered artifacts. Default is a dry run.")
    parser.add_argument("--include-vsix", action="store_true", help="Deprecated: old VSIX files are included by default.")
    parser.add_argument("--skip-vsix", action="store_true", help="Do not report old VSIX files.")
    parser.add_argument("--include-current-vsix", action="store_true", help="Also report the current versioned VSIX.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    paths = package_artifacts(
        root,
        include_vsix=not args.skip_vsix or args.include_vsix,
        include_current_vsix=args.include_current_vsix,
    )
    for message in cleanup_messages(root, paths, apply=args.apply):
        print(message)
    if args.apply:
        clean(paths)
    return 0


def _current_vsix_path(root: Path) -> Path | None:
    package_path = root / "vscode-extension" / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        name = package["name"]
        version = package["version"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return (root / "vscode-extension" / f"{name}-{version}.vsix").resolve()


if __name__ == "__main__":
    sys.exit(main())
