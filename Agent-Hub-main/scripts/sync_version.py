from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def sync_version(root: Path, version: str) -> list[str]:
    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"Version must be semver-like, got {version!r}")

    changed: list[str] = []
    changed.extend(_update_release(root / "release.json", version))
    changed.extend(_update_package(root / "vscode-extension" / "package.json", version))
    changed.extend(_update_package_lock(root / "vscode-extension" / "package-lock.json", version))
    changed.extend(_replace_regex(root / "pyproject.toml", r'(?m)^version\s*=\s*"[^"]+"', f'version = "{version}"'))
    changed.extend(
        _replace_regex(
            root / "agent_hub" / "version.py",
            r'(?m)^BASE_VERSION\s*=\s*"[^"]+"',
            f'BASE_VERSION = "{version}"',
        )
    )
    changed.extend(_update_current_docs(root, version))
    return changed


def _update_release(path: Path, version: str) -> list[str]:
    data = _read_json(path)
    data["extension_version"] = version
    data["backend_version"] = version
    data["minimum_supported_backend_version"] = version
    build = data.setdefault("build", {})
    if not isinstance(build, dict):
        data["build"] = build = {}
    build.setdefault("metadata_source", "release.json")
    build.setdefault("backend_snapshot_manifest", "vscode-extension/backend/SNAPSHOT.json")
    build.setdefault("canonical_backend", "agent_hub")
    build.setdefault("commit_sha", "")
    build.setdefault("build_timestamp_utc", "")
    build.setdefault("git_tag", "")
    return _write_json_if_changed(path, data)


def _update_package(path: Path, version: str) -> list[str]:
    data = _read_json(path)
    data["version"] = version
    return _write_json_if_changed(path, data)


def _update_package_lock(path: Path, version: str) -> list[str]:
    data = _read_json(path)
    data["version"] = version
    packages = data.get("packages")
    if isinstance(packages, dict) and isinstance(packages.get(""), dict):
        packages[""]["version"] = version
    return _write_json_if_changed(path, data)


def _update_current_docs(root: Path, version: str) -> list[str]:
    changed: list[str] = []
    docs = [
        root / "docs" / "screenshots" / "README.md",
    ]
    for path in docs:
        changed.extend(_replace_regex(path, r"\b\d+\.\d+\.\d+\b", version))
    changelog = root / "vscode-extension" / "CHANGELOG.md"
    if changelog.exists():
        text = changelog.read_text(encoding="utf-8")
        heading = f"## {version}"
        if heading not in text:
            text = text.replace(
                "# Changelog\n\n",
                (
                    "# Changelog\n\n"
                    f"{heading}\n\n"
                    "- Syncs extension and backend release metadata for the next package.\n"
                    "- Adds install verification, packaging checks, and command-runner hardening.\n\n"
                ),
                1,
            )
            if _write_text_if_changed(changelog, text):
                changed.append(_rel(changelog))
    return changed


def _replace_regex(path: Path, pattern: str, replacement: str) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text)
    if count and _write_text_if_changed(path, updated):
        return [_rel(path)]
    return []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {_rel(path)}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{_rel(path)} must contain a JSON object")
    return data


def _write_json_if_changed(path: Path, data: dict[str, Any]) -> list[str]:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return [_rel(path)] if _write_text_if_changed(path, text) else []


def _write_text_if_changed(path: Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize Agent Hub release and package versions.")
    parser.add_argument("version", help="Canonical semver version, for example 0.7.25.")
    args = parser.parse_args(argv)
    try:
        changed = sync_version(ROOT, args.version)
    except ValueError as exc:
        print(f"Version sync failed: {exc}", file=sys.stderr)
        return 1
    if changed:
        print(f"Synchronized version {args.version} in:")
        for path in changed:
            print(f"- {path}")
    else:
        print(f"Version already synchronized at {args.version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
