from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.dependency_audit import validate_dependency_declarations
from agent_hub.config_reference import generate_config_reference
from scripts.backend_snapshot import REQUIRED_SNAPSHOT_FILES, build_manifest, source_files, validate_snapshot
from scripts.validate_vsix_cleanliness import expected_vsix_path, validate_vsix


VERSIONED_VSIX_PATTERN = re.compile(r"agent-hub-vscode-\d+\.\d+\.\d+(?:[-.\w]*)?\.vsix")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")
PACKAGE_TEST_SENTINEL = "AGENT_HUB_VALIDATE_RELEASE_PACKAGE_TESTS"
FORBIDDEN_MEDIA_REFERENCE_PATTERNS = (
    re.compile(r"gpt[-_\s]?image", re.IGNORECASE),
    re.compile(r"image" + r"[-_\s]?generation", re.IGNORECASE),
    re.compile(r"\bimages\.generate\b", re.IGNORECASE),
    re.compile(r"generated" + r"\s+screenshots?", re.IGNORECASE),
)
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SKIPPED_SCAN_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".venv-check",
    "__pycache__",
    "node_modules",
    "backend",
    "build",
    "agent_hub.egg-info",
}


def validate_release(
    root: Path,
    *,
    require_vsix: bool = False,
    run_package_tests: bool = False,
) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    release = read_json(root / "release.json")
    package = read_json(root / "vscode-extension" / "package.json")
    lock = read_json(root / "vscode-extension" / "package-lock.json")
    pyproject = read_toml(root / "pyproject.toml")
    pyproject_version = read_toml_version(root / "pyproject.toml")
    backend_base_version = read_backend_base_version(root / "agent_hub" / "version.py")

    failures.extend(validate_release_metadata(release))
    failures.extend(validate_pyproject_metadata(pyproject))
    failures.extend(validate_dependency_declarations(root, pyproject))
    failures.extend(validate_extension_packaging_scripts(package))
    failures.extend(validate_backend_generation_documented(root))
    failures.extend(validate_backend_snapshot_generation(root))
    failures.extend(validate_no_forbidden_media_references(root))
    failures.extend(validate_no_dangerous_shell_true(root))
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
    if run_package_tests:
        failures.extend(validate_package_tests(root))

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
    for key in (
        "extension_version",
        "backend_version",
        "minimum_supported_backend_version",
    ):
        if release.get(key) and not _valid_version(str(release[key])):
            failures.append(f"release.json {key} must be a valid version")

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


def validate_pyproject_metadata(pyproject: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    project = pyproject.get("project") if isinstance(pyproject, dict) else {}
    build_system = pyproject.get("build-system") if isinstance(pyproject, dict) else {}
    if not isinstance(project, dict):
        return ["pyproject.toml project metadata must be an object"]

    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        failures.append("pyproject.toml project.dependencies must be a list")

    optional = project.get("optional-dependencies")
    dev_deps = optional.get("dev") if isinstance(optional, dict) else []
    if not isinstance(dev_deps, list):
        failures.append("pyproject.toml optional dev dependencies must be a list")
    else:
        normalized = _dependency_names(dev_deps)
        for dependency in ("build",):
            if dependency not in normalized:
                failures.append(f"pyproject.toml dev extra is missing {dependency}")
        for dependency in ("pytest", "pytest-timeout"):
            if dependency in normalized:
                failures.append(f"pyproject.toml dev extra should not include test-only dependency {dependency}")

    test_deps = optional.get("test") if isinstance(optional, dict) else []
    if not isinstance(test_deps, list):
        failures.append("pyproject.toml optional test dependencies must be a list")
    else:
        normalized = _dependency_names(test_deps)
        for dependency in ("pytest", "pytest-timeout"):
            if dependency not in normalized:
                failures.append(f"pyproject.toml test extra is missing {dependency}")

    release_deps = optional.get("release") if isinstance(optional, dict) else []
    if not isinstance(release_deps, list):
        failures.append("pyproject.toml optional release dependencies must be a list")
    else:
        normalized = _dependency_names(release_deps)
        for dependency in ("build", "packaging"):
            if dependency not in normalized:
                failures.append(f"pyproject.toml release extra is missing {dependency}")

    scripts = project.get("scripts")
    if not isinstance(scripts, dict) or scripts.get("agent-hub") != "agent_hub.cli:main":
        failures.append("pyproject.toml must expose agent-hub = agent_hub.cli:main")

    if project.get("requires-python") != ">=3.11":
        failures.append("pyproject.toml requires-python must be >=3.11")

    build_requires = build_system.get("requires") if isinstance(build_system, dict) else []
    if not isinstance(build_requires, list) or not any(str(item).startswith("setuptools") for item in build_requires):
        failures.append("pyproject.toml build-system must require setuptools")
    return failures


def validate_extension_packaging_scripts(package: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    if not isinstance(scripts, dict):
        return ["vscode-extension/package.json scripts must be an object"]
    for name in ("prepare-backend", "validate-backend-drift", "package", "publish", "vscode:prepublish"):
        if not scripts.get(name):
            failures.append(f"vscode-extension/package.json scripts is missing {name}")
    for name in ("package", "publish", "vscode:prepublish"):
        command = str(scripts.get(name) or "")
        if "prepare-backend" not in command:
            failures.append(f"vscode-extension/package.json {name} script must run prepare-backend")
    for name in ("package", "vscode:prepublish"):
        command = str(scripts.get(name) or "")
        if "validate-backend-drift" not in command:
            failures.append(f"vscode-extension/package.json {name} script must validate backend drift")
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
    for label, value in (
        ("package.json version", package_version),
        ("pyproject.toml version", pyproject_version),
        ("agent_hub/version.py BASE_VERSION", backend_base_version),
    ):
        if value and not _valid_version(str(value)):
            failures.append(f"{label} must be a valid version")
    return failures


def validate_release_docs(root: Path) -> list[str]:
    failures: list[str] = []
    required_docs = [
        root / "README.md",
        root / "CONTRIBUTING.md",
        root / "docs" / "backend-snapshot.md",
        root / "docs" / "api.md",
        root / "docs" / "architecture.md",
    ]
    for path in required_docs:
        if not path.exists():
            failures.append(f"required documentation is missing: {path.relative_to(root).as_posix()}")
    release_docs = [
        root / "docs" / "PUBLISHING.md",
        root / "docs" / "install-vsix.md",
        root / "vscode-extension" / "PUBLISHING.md",
    ]
    for path in release_docs:
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


def validate_backend_generation_documented(root: Path) -> list[str]:
    failures: list[str] = []
    docs = {
        "docs/backend-snapshot.md": root / "docs" / "backend-snapshot.md",
        "docs/PUBLISHING.md": root / "docs" / "PUBLISHING.md",
        "README.md": root / "README.md",
    }
    required = ("generate_backend_snapshot.py", "npm run prepare-backend", "validate_backend_drift.py")
    for rel, path in docs.items():
        if not path.exists():
            failures.append(f"backend generation documentation is missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in required:
            if marker not in text:
                failures.append(f"{rel} does not document backend generation marker: {marker}")
    return failures


def validate_backend_snapshot_generation(root: Path) -> list[str]:
    failures: list[str] = []
    try:
        files = source_files(root)
        manifest = build_manifest(root, files=files)
    except Exception as exc:
        return [f"backend snapshot generation failed before writing files: {exc}"]
    paths = {item.relative_path for item in files}
    for required in REQUIRED_SNAPSHOT_FILES:
        if required not in paths:
            failures.append(f"backend snapshot generation source is missing required file: {required}")
    if not manifest.get("tree_sha256") or manifest.get("file_count", 0) <= 0:
        failures.append("backend snapshot generation did not produce a valid manifest")
    if manifest.get("generated_by") != "scripts/generate_backend_snapshot.py":
        failures.append("backend snapshot manifest generated_by marker is unexpected")
    return failures


def validate_no_forbidden_media_references(root: Path) -> list[str]:
    failures: list[str] = []
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in FORBIDDEN_MEDIA_REFERENCE_PATTERNS:
            if pattern.search(text):
                failures.append(
                    f"forbidden generated-media reference in {_rel(root, path)}: {pattern.pattern}"
                )
                break
    return failures


def validate_no_dangerous_shell_true(root: Path) -> list[str]:
    failures: list[str] = []
    for path in _iter_text_files(root):
        if path.suffix.lower() != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    failures.append(f"dangerous shell={'True'} in {_rel(root, path)}:{node.lineno}")
    return failures


def validate_package_tests(root: Path) -> list[str]:
    if os.environ.get(PACKAGE_TEST_SENTINEL) == "1":
        return []
    env = os.environ.copy()
    env[PACKAGE_TEST_SENTINEL] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "packaging"],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    except FileNotFoundError:
        return ["package tests could not run because pytest is not installed"]
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "").strip()
        detail = f": {_last_output_lines(output)}" if output else ""
        return [f"package tests timed out{detail}"]
    if completed.returncode == 0:
        return []
    return [f"package tests failed: {_last_output_lines(completed.stdout)}"]


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_toml(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
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


def _valid_version(value: str) -> bool:
    try:
        Version(value)
    except InvalidVersion:
        return False
    return True


def _dependency_names(dependencies: list[Any]) -> set[str]:
    names: set[str] = set()
    for item in dependencies:
        if not isinstance(item, str):
            continue
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", item)
        if match:
            names.add(match.group(1))
    return names


def _iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIPPED_SCAN_PARTS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "LICENSE", "README"}:
            files.append(path)
    return files


def _last_output_lines(output: str, *, limit: int = 8) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return " | ".join(lines[-limit:])


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Agent Hub release metadata and packaging drift.")
    parser.add_argument("--require-vsix", action="store_true", help="Fail if the current versioned VSIX is missing.")
    args = parser.parse_args(argv)
    failures = validate_release(ROOT, require_vsix=args.require_vsix, run_package_tests=True)
    if failures:
        print("Release validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Release metadata and packaging drift checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
