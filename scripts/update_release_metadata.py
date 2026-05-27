from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def update_release_metadata(
    root: Path,
    *,
    commit_sha: str | None = None,
    build_timestamp_utc: str | None = None,
    git_tag: str | None = None,
    from_ci_env: bool = False,
) -> dict[str, Any]:
    path = root / "release.json"
    release = read_json(path)
    build = release.setdefault("build", {})
    if not isinstance(build, dict):
        build = {}
        release["build"] = build

    if from_ci_env:
        commit_sha = commit_sha or os.environ.get("AGENT_HUB_BUILD_COMMIT_SHA") or os.environ.get("GITHUB_SHA")
        git_tag = git_tag if git_tag is not None else _ci_git_tag()
        build_timestamp_utc = (
            build_timestamp_utc
            or os.environ.get("AGENT_HUB_BUILD_TIMESTAMP_UTC")
            or _utc_now()
        )

    if commit_sha is None:
        commit_sha = _git_output(root, "rev-parse", "HEAD")
    if build_timestamp_utc is None:
        build_timestamp_utc = _utc_now()
    if git_tag is None:
        git_tag = _git_output(root, "describe", "--tags", "--exact-match")

    if commit_sha:
        build["commit_sha"] = commit_sha.strip()
    if build_timestamp_utc:
        build["build_timestamp_utc"] = build_timestamp_utc.strip()
    build["git_tag"] = git_tag.strip() if git_tag else ""

    path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return release


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ci_git_tag() -> str:
    explicit = os.environ.get("AGENT_HUB_BUILD_GIT_TAG")
    if explicit is not None:
        return explicit
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        return os.environ.get("GITHUB_REF_NAME", "")
    return ""


def _git_output(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inject build metadata into release.json.")
    parser.add_argument("--from-ci-env", action="store_true", help="Read GitHub Actions metadata from the environment.")
    parser.add_argument("--commit-sha", help="Git commit SHA to write into release.json.")
    parser.add_argument("--build-timestamp-utc", help="ISO UTC build timestamp to write into release.json.")
    parser.add_argument("--git-tag", help="Git tag to write into release.json; use an empty string when untagged.")
    args = parser.parse_args(argv)
    release = update_release_metadata(
        ROOT,
        commit_sha=args.commit_sha,
        build_timestamp_utc=args.build_timestamp_utc,
        git_tag=args.git_tag,
        from_ci_env=args.from_ci_env,
    )
    build = release.get("build", {})
    print(
        "Updated release metadata: "
        f"commit={build.get('commit_sha', '')[:12] or 'none'} "
        f"tag={build.get('git_tag', '') or 'none'} "
        f"timestamp={build.get('build_timestamp_utc', '') or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
