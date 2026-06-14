from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bghp_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|x-api-key|api-key|access[_-]?token|refresh[_-]?token|secret|password)\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{8,})"
)
LONG_TOKEN_PATTERN = re.compile(
    r"\b(?=[A-Za-z0-9._~+/=-]{40,}\b)(?=[A-Za-z0-9._~+/=-]*[A-Za-z])(?=[A-Za-z0-9._~+/=-]*\d)(?=[A-Za-z0-9._~+/=-]*[._~+/=-])[A-Za-z0-9._~+/=-]{40,}\b"
)
LOCAL_PATH_PATTERN = re.compile(r"([A-Za-z]:[\\/](?:Users|Documents)[\\/]|/Users/[^/\s]+/|/home/[^/\s]+/)")
PRODUCTION_TEST_NAMED_MODULES = {
    "extension/backend/agent_hub/repo_dna/test_detector.py",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate packaged VSIX cleanliness.")
    parser.add_argument("vsix", nargs="?", help="Path to the VSIX to inspect.")
    parser.add_argument("--check-source", action="store_true", help="Also fail if stray .vsix files are present in the source tree.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    vsix_path = Path(args.vsix).resolve() if args.vsix else expected_vsix_path(root)
    failures = validate_vsix(vsix_path, root=root)
    if args.check_source:
        failures.extend(validate_source_vsix_files(root, expected=vsix_path))

    if failures:
        print(f"VSIX cleanliness check failed for {vsix_path}:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"VSIX cleanliness check passed: {vsix_path}")
    return 0


def expected_vsix_path(root: Path) -> Path:
    package_path = root / "vscode-extension" / "package.json"
    manifest = json.loads(package_path.read_text(encoding="utf-8"))
    return root / "vscode-extension" / f"{manifest['name']}-{manifest['version']}.vsix"


def validate_vsix(vsix_path: Path, *, root: Path) -> list[str]:
    failures: list[str] = []
    if not vsix_path.exists():
        return [f"VSIX does not exist: {vsix_path}"]
    manifest = json.loads((root / "vscode-extension" / "package.json").read_text(encoding="utf-8"))
    runtime_dependencies = bool(manifest.get("dependencies"))
    try:
        archive = zipfile.ZipFile(vsix_path)
    except zipfile.BadZipFile:
        return [f"VSIX is not a readable zip archive: {vsix_path}"]
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        total_bytes = sum(info.file_size for info in infos)
        if total_bytes > MAX_TOTAL_BYTES:
            failures.append(f"archive is oversized: {total_bytes} bytes")
        for info in infos:
            name = info.filename.replace("\\", "/")
            lower = name.lower()
            parts = [part for part in lower.split("/") if part]
            basename = parts[-1] if parts else lower
            if lower.endswith(".vsix"):
                failures.append(f"old VSIX nested in package: {name}")
            if "node_modules" in parts and not runtime_dependencies:
                failures.append(f"node_modules included without runtime dependencies: {name}")
            if basename == ".env" or basename.startswith(".env."):
                failures.append(f"environment file included: {name}")
            if _backup_config_name(basename):
                failures.append(f"backup or local config included: {name}")
            if _dev_artifact(parts):
                failures.append(f"development artifact included: {name}")
            if _test_artifact(parts, basename) and lower not in PRODUCTION_TEST_NAMED_MODULES:
                failures.append(f"test artifact included: {name}")
            if _temp_artifact(basename):
                failures.append(f"temporary file included: {name}")
            if info.file_size > MAX_FILE_BYTES:
                failures.append(f"oversized file included ({info.file_size} bytes): {name}")
            if _should_scan_text(name):
                failures.extend(_scan_text_member(archive, info, name))
    return failures


def validate_source_vsix_files(root: Path, *, expected: Path) -> list[str]:
    failures: list[str] = []
    expected = expected.resolve()
    for path in root.rglob("*.vsix"):
        resolved = path.resolve()
        if "node_modules" in path.parts:
            continue
        if resolved != expected:
            failures.append(f"stray source VSIX file: {path.relative_to(root)}")
    return failures


def _scan_text_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, name: str) -> list[str]:
    failures: list[str] = []
    try:
        data = archive.read(info)
    except KeyError:
        return failures
    if b"\x00" in data[:4096]:
        return failures
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return failures
    if LOCAL_PATH_PATTERN.search(text):
        failures.append(f"local absolute path found in {name}")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            failures.append(f"secret-looking string found in {name}")
            break
    if _secret_assignment_found(text):
        failures.append(f"secret-looking string found in {name}")
    if _long_token_found(text, name=name):
        failures.append(f"long token-looking string found in {name}")
    return failures


def _should_scan_text(name: str) -> bool:
    path = Path(name)
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in {"LICENSE", "NOTICE"}


def _backup_config_name(basename: str) -> bool:
    return (
        basename.endswith(".bak")
        or basename.endswith(".backup")
        or basename.endswith(".config.backup.json")
        or basename.endswith(".config.local.json")
        or basename == "agent-hub.config.json"
    )


def _dev_artifact(parts: Iterable[str]) -> bool:
    return any(part in {".git", ".vscode", ".vscode-test", ".pytest_cache", "__pycache__"} for part in parts)


def _test_artifact(parts: list[str], basename: str) -> bool:
    return (
        "tests" in parts
        or "__tests__" in parts
        or basename.startswith("test_")
        or basename.endswith(".test.js")
        or basename.endswith(".spec.js")
    )


def _temp_artifact(basename: str) -> bool:
    return (
        basename.endswith("~")
        or basename.endswith(".tmp")
        or basename.endswith(".temp")
        or basename.endswith(".swp")
        or basename in {".ds_store", "thumbs.db"}
    )


def _secret_assignment_found(text: str) -> bool:
    for match in SECRET_ASSIGNMENT_PATTERN.finditer(text):
        value = match.group(2).strip()
        if _looks_like_real_secret_value(value):
            return True
    return False


def _looks_like_real_secret_value(value: str) -> bool:
    if value.startswith("agentHub.") or value.startswith("${"):
        return False
    if value in {"api_key", "request_headers", "headers"}:
        return False
    if value.upper() == value and "_" in value:
        return False
    if len(value) < 16:
        return False
    return bool(re.search(r"\d", value) and re.search(r"[._~+/=-]", value))


def _long_token_found(text: str, *, name: str) -> bool:
    if name.lower().endswith(("package-lock.json", ".md")):
        return False
    for line in text.splitlines():
        lowered = line.lower()
        if "http://" in lowered or "https://" in lowered:
            continue
        if not any(marker in lowered for marker in ("token", "secret", "api_key", "api-key", "authorization", "bearer")):
            continue
        if LONG_TOKEN_PATTERN.search(line):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
