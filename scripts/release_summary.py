from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    release = read_json(ROOT / "release.json")
    package = read_json(ROOT / "vscode-extension" / "package.json")
    snapshot = read_json(ROOT / "vscode-extension" / "backend" / "SNAPSHOT.json")
    build = release.get("build", {})
    build = build if isinstance(build, dict) else {}
    print("Agent Hub Release Summary")
    print(f"- Extension version: {release.get('extension_version') or package.get('version') or 'unknown'}")
    print(f"- Backend version: {release.get('backend_version') or 'unknown'}")
    print(f"- Protocol/API compatibility: {release.get('protocol_api_compatibility_version') or 'unknown'}")
    print(f"- Minimum backend: {release.get('minimum_supported_backend_version') or 'unknown'}")
    print(f"- Release timestamp: {release.get('release_timestamp_utc') or 'unknown'}")
    print(f"- Build timestamp: {build.get('build_timestamp_utc') or 'not stamped'}")
    print(f"- Build commit: {build.get('commit_sha') or 'not stamped'}")
    print(f"- Build tag: {build.get('git_tag') or 'not tagged'}")
    print(f"- Backend snapshot files: {snapshot.get('file_count', 'unknown')}")
    print(f"- Backend snapshot checksum: {snapshot.get('tree_sha256', 'unknown')}")
    print(f"- Git commit: {_git_value(['rev-parse', '--short', 'HEAD']) or 'unknown'}")
    print(f"- Git dirty: {'yes' if _git_value(['status', '--short']) else 'no'}")
    return 0


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


if __name__ == "__main__":
    sys.exit(main())
