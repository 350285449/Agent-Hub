from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config_reference import generate_config_reference
from scripts.backend_snapshot import validate_snapshot
from scripts.validate_vsix_cleanliness import expected_vsix_path, validate_vsix


VERSIONED_VSIX_PATTERN = re.compile(r"agent-hub-vscode-\d+\.\d+\.\d+(?:[-.\w]*)?\.vsix")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


def validate_release(root: Path, *, require_vsix: bool = False) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    release = read_json(root / "release.json")
    package = read_json(root / "vscode-extension" / "package.json")
    lock = read_json(root / "vscode-extension" / "package-lock.json")
    pyproject_version = read_toml_version(root / "pyproject.toml")
    backend_base_version = read_backend_base_version(root / "agent_hub" / "version.py")

    failures.extend(validate_release_metadata(release))
    failures.extend(
        validate_version_consistency(
            release=release,
            package=package,
            lock=lock,
            pyproject_version=pyproject_version,
            backend_base_version=backend_base_version,
        )
    )

    reference_path = root / "docs" / "config-reference.md"
    if reference_path.exists() and reference_path.read_text(encoding="utf-8") != generate_config_reference():
        failures.append("docs/config-reference.md is stale")

    failures.extend(validate_snapshot(root))
    failures.extend(validate_release_docs(root))

    vsix_path = expected_vsix_path(root)
    if vsix_path.exists():
        failures.extend(validate_vsix(vsix_path, root=root))
    elif require_vsix:
        failures.append(f"expected VSIX is missing: {vsix_path}")
    return failures


def validate_release_metadata(release: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in (
        "schema_version",
        "name",
        "extension_version",
        "backend_version",
        "protocol_api_compatibility_version",
        "minimum_supported_backend_version",
        "release_timestamp_utc",
    ):
        if not release.get(key):
            failures.append(f"release.json is missing {key}")
    if release.get("release_timestamp_utc") and not _valid_utc_timestamp(str(release["release_timestamp_utc"])):
        failures.append("release.json release_timestamp_utc must be an ISO UTC timestamp")

    build = release.get("build")
    if not isinstance(build, dict):
        failures.append("release.json build metadata must be an object")
        return failures
    for key in ("metadata_source", "backend_snapshot_manifest", "canonical_backend"):
        if not build.get(key):
            failures.append(f"release.json build metadata is missing {key}")
    commit_sha = build.get("commit_sha")
    if commit_sha and not COMMIT_SHA_PATTERN.fullmatch(str(commit_sha)):
        failures.append("release.json build.commit_sha must be a 7-40 character git SHA")
    build_timestamp = build.get("build_timestamp_utc")
    if build_timestamp and not _valid_utc_timestamp(str(build_timestamp)):
        failures.append("release.json build.build_timestamp_utc must be an ISO UTC timestamp")
    git_tag = build.get("git_tag")
    if git_tag is not None and not isinstance(git_tag, str):
        failures.append("release.json build.git_tag must be a string")
    return failures


def validate_version_consistency(
    *,
    release: dict[str, Any],
    package: dict[str, Any],
    lock: dict[str, Any],
    pyproject_version: str,
    backend_base_version: str,
) -> list[str]:
    failures: list[str] = []
    package_version = package.get("version")
    if release.get("extension_version") != package_version:
        failures.append("release.json extension_version does not match vscode-extension/package.json")
    if lock.get("version") != package_version:
        failures.append("package-lock.json version does not match package.json")
    lock_root = lock.get("packages", {}).get("") if isinstance(lock.get("packages"), dict) else {}
    if not isinstance(lock_root, dict) or lock_root.get("version") != package_version:
        failures.append("package-lock root package version does not match package.json")
    if release.get("backend_version") != pyproject_version:
        failures.append("release.json backend_version does not match pyproject.toml")
    if backend_base_version != pyproject_version:
        failures.append("agent_hub/version.py BASE_VERSION does not match pyproject.toml")
    if package_version != pyproject_version:
        failures.append("vscode-extension/package.json version does not match pyproject.toml")
    if release.get("minimum_supported_backend_version") != release.get("backend_version"):
        failures.append("minimum_supported_backend_version should match backend_version for Phase 9")
    return failures


def validate_release_docs(root: Path) -> list[str]:
    failures: list[str] = []
    docs = [
        root / "docs" / "PUBLISHING.md",
        root / "docs" / "install-vsix.md",
        root / "vscode-extension" / "PUBLISHING.md",
    ]
    for path in docs:
        if not path.exists():
            failures.append(f"release documentation is missing: {path.relative_to(root).as_posix()}")
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        if "release.json" not in text:
            failures.append(f"{rel} does not reference release.json")
        if VERSIONED_VSIX_PATTERN.search(text):
            failures.append(f"{rel} contains a hardcoded VSIX version")
    install = (root / "docs" / "install-vsix.md").read_text(encoding="utf-8") if (root / "docs" / "install-vsix.md").exists() else ""
    publishing = (root / "vscode-extension" / "PUBLISHING.md").read_text(encoding="utf-8") if (root / "vscode-extension" / "PUBLISHING.md").exists() else ""
    for marker in ("agent-hub-vscode-<version>.vsix", "validate_backend_drift.py"):
        if marker not in install and marker not in publishing:
            failures.append(f"release docs do not include shared marker: {marker}")
    return failures


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_toml_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def read_backend_base_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^\s*BASE_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def _valid_utc_timestamp(value: str) -> bool:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Agent Hub release metadata and packaging drift.")
    parser.add_argument("--require-vsix", action="store_true", help="Fail if the current versioned VSIX is missing.")
    args = parser.parse_args(argv)
    failures = validate_release(ROOT, require_vsix=args.require_vsix)
    if failures:
        print("Release validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Release metadata and packaging drift checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
