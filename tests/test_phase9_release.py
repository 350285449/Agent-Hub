from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.backend_snapshot import generate_snapshot, validate_snapshot
from scripts.package_clean import cleanup_messages
from scripts.update_release_metadata import update_release_metadata
from scripts.validate_release import (
    validate_dependency_declarations,
    validate_extension_packaging_scripts,
    validate_pyproject_metadata,
    validate_release_metadata,
    validate_version_consistency,
)


class PhaseNineReleaseMetadataTests(unittest.TestCase):
    def test_release_metadata_validation_accepts_ci_build_fields(self) -> None:
        release = _release_manifest()
        release["build"].update(
            {
                "commit_sha": "0123456789abcdef",
                "build_timestamp_utc": "2026-05-27T12:00:00Z",
                "git_tag": "v0.7.7",
            }
        )

        self.assertEqual(validate_release_metadata(release), [])

    def test_release_metadata_validation_rejects_invalid_ci_build_fields(self) -> None:
        release = _release_manifest()
        release["build"].update(
            {
                "commit_sha": "not-a-sha",
                "build_timestamp_utc": "tomorrow",
                "git_tag": 7,
            }
        )

        failures = validate_release_metadata(release)

        self.assertTrue(any("build.commit_sha" in item for item in failures))
        self.assertTrue(any("build.build_timestamp_utc" in item for item in failures))
        self.assertTrue(any("build.git_tag" in item for item in failures))

    def test_update_release_metadata_injects_build_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "release.json").write_text(json.dumps(_release_manifest()), encoding="utf-8")

            release = update_release_metadata(
                root,
                commit_sha="abcdef1234567890",
                build_timestamp_utc="2026-05-27T12:00:00Z",
                git_tag="v0.7.7",
            )

            build = release["build"]
            self.assertEqual(build["commit_sha"], "abcdef1234567890")
            self.assertEqual(build["build_timestamp_utc"], "2026-05-27T12:00:00Z")
            self.assertEqual(build["git_tag"], "v0.7.7")

    def test_package_lock_version_consistency_is_enforced(self) -> None:
        release = _release_manifest()
        package = {"version": "0.7.7"}
        lock = {"version": "0.7.6", "packages": {"": {"version": "0.7.6"}}}

        failures = validate_version_consistency(
            release=release,
            package=package,
            lock=lock,
            pyproject_version="0.7.7",
            backend_base_version="0.7.7",
        )

        self.assertTrue(any("package-lock.json version" in item for item in failures))
        self.assertTrue(any("package-lock root package version" in item for item in failures))

    def test_pyproject_metadata_validation_requires_runtime_and_test_dependencies(self) -> None:
        pyproject = _pyproject_metadata()

        self.assertEqual(validate_pyproject_metadata(pyproject), [])

        pyproject["project"]["optional-dependencies"]["test"] = ["pytest>=8.0"]
        pyproject["project"]["optional-dependencies"]["release"] = ["packaging>=24.0"]

        failures = validate_pyproject_metadata(pyproject)

        self.assertTrue(any("pytest-timeout" in item for item in failures))
        self.assertTrue(any("release extra is missing build" in item for item in failures))

    def test_dependency_declaration_validation_matches_runtime_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "agent_hub"
            package.mkdir()
            (package / "__init__.py").write_text("import email\nimport packaging.version\n", encoding="utf-8")
            pyproject = _pyproject_metadata()

            self.assertEqual(validate_dependency_declarations(root, pyproject), [])

            (package / "network.py").write_text("import requests\n", encoding="utf-8")
            failures = validate_dependency_declarations(root, pyproject)

            self.assertTrue(any("missing runtime dependency for import requests" in item for item in failures))

    def test_extension_packaging_scripts_prepare_backend_snapshot(self) -> None:
        package = {
            "scripts": {
                "prepare-backend": "node scripts/prepare-backend.js",
                "validate-backend-drift": "python ../scripts/validate_backend_drift.py",
                "package": "npm run prepare-backend && npm run validate-backend-drift && npx @vscode/vsce package",
                "publish": "npm run prepare-backend && npm run validate-release && npx @vscode/vsce publish",
                "vscode:prepublish": "npm run prepare-backend && npm run validate-backend-drift",
            }
        }

        self.assertEqual(validate_extension_packaging_scripts(package), [])

        package["scripts"]["vscode:prepublish"] = "npm run validate-backend-drift"
        failures = validate_extension_packaging_scripts(package)

        self.assertTrue(any("vscode:prepublish script must run prepare-backend" in item for item in failures))


class PhaseNineSnapshotEnforcementTests(unittest.TestCase):
    def test_snapshot_required_files_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot_fixture(Path(tmp))
            generate_snapshot(root)
            (root / "vscode-extension" / "backend" / "agent_hub" / "version.py").unlink()

            failures = validate_snapshot(root)

            self.assertTrue(any("required snapshot file missing: agent_hub/version.py" in item for item in failures))

    def test_forbidden_snapshot_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot_fixture(Path(tmp))
            generate_snapshot(root)
            forbidden = root / "vscode-extension" / "backend" / "agent_hub" / "__pycache__" / "bad.pyc"
            forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b"bad")

            failures = validate_snapshot(root)

            self.assertTrue(any("forbidden snapshot file" in item for item in failures))


class PhaseNinePackageCleanupTests(unittest.TestCase):
    def test_cleanup_dry_run_reports_without_removing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "vscode-extension" / "old.vsix"
            artifact.parent.mkdir()
            artifact.write_text("old", encoding="utf-8")

            messages = cleanup_messages(root, [artifact], apply=False)

            self.assertIn(f"Would remove: {Path('vscode-extension') / 'old.vsix'}", messages)
            self.assertTrue(messages[-1].startswith("Dry run only."))
            self.assertTrue(artifact.exists())


def _release_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "agent-hub",
        "extension_version": "0.7.7",
        "backend_version": "0.7.7",
        "protocol_api_compatibility_version": "1",
        "minimum_supported_backend_version": "0.7.7",
        "release_timestamp_utc": "2026-05-27T00:00:00Z",
        "build": {
            "metadata_source": "release.json",
            "backend_snapshot_manifest": "vscode-extension/backend/SNAPSHOT.json",
            "canonical_backend": "agent_hub",
        },
    }


def _pyproject_metadata() -> dict[str, object]:
    return {
        "build-system": {"requires": ["setuptools>=69"]},
        "project": {
            "name": "agent-hub",
            "version": "0.7.7",
            "requires-python": ">=3.11",
            "dependencies": ["packaging>=24.0"],
            "optional-dependencies": {
                "release": ["build>=1.2", "packaging>=24.0"],
                "test": ["pytest>=8.0", "pytest-timeout>=2.3"],
            },
            "scripts": {
                "agent-hub": "agent_hub.cli:main",
            },
        },
    }


def _snapshot_fixture(root: Path) -> Path:
    package = root / "agent_hub"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "__main__.py").write_text("print('ok')\n", encoding="utf-8")
    (package / "version.py").write_text("BASE_VERSION = \"0.1.0\"\n", encoding="utf-8")
    (root / "vscode-extension" / "backend").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"agent-hub\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "release.json").write_text(json.dumps(_release_manifest()), encoding="utf-8")
    return root


if __name__ == "__main__":
    unittest.main()
