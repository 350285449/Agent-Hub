from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.backend_snapshot import generate_snapshot, validate_snapshot
from scripts.package_clean import package_artifacts
from scripts.validate_release import validate_release
from scripts.validate_vsix_cleanliness import validate_vsix


ROOT = Path(__file__).resolve().parents[1]


class PhaseEightBackendSnapshotTests(unittest.TestCase):
    def test_snapshot_generation_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot_fixture(Path(tmp))

            first = generate_snapshot(root)
            first_manifest = (root / "vscode-extension" / "backend" / "SNAPSHOT.json").read_text(encoding="utf-8")
            second = generate_snapshot(root)
            second_manifest = (root / "vscode-extension" / "backend" / "SNAPSHOT.json").read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(validate_snapshot(root), [])

    def test_snapshot_drift_detection_catches_modified_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot_fixture(Path(tmp))
            generate_snapshot(root)
            snapshot_file = root / "vscode-extension" / "backend" / "agent_hub" / "__init__.py"
            snapshot_file.write_text("DRIFT = True\n", encoding="utf-8")

            failures = validate_snapshot(root)

            self.assertTrue(any("snapshot file drift: agent_hub/__init__.py" in item for item in failures))


class PhaseEightReleaseValidationTests(unittest.TestCase):
    def test_release_manifest_consistency(self) -> None:
        generate_snapshot(ROOT)
        failures = validate_release(ROOT, require_vsix=False)

        self.assertEqual(failures, [])

    def test_package_validation_rejects_unwanted_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extension = root / "vscode-extension"
            extension.mkdir()
            (extension / "package.json").write_text(
                json.dumps({"name": "agent-hub-vscode", "version": "0.0.1"}),
                encoding="utf-8",
            )
            vsix = extension / "agent-hub-vscode-0.0.1.vsix"
            with zipfile.ZipFile(vsix, "w") as archive:
                archive.writestr("extension/old.vsix", "old")
                archive.writestr("extension/.env", "SECRET=value")
                archive.writestr("extension/tests/test_demo.py", "pass")

            failures = validate_vsix(vsix, root=root)

            self.assertTrue(any("old VSIX nested" in item for item in failures))
            self.assertTrue(any("environment file included" in item for item in failures))
            self.assertTrue(any("test artifact included" in item for item in failures))

    def test_package_clean_reports_old_vsix_without_current_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extension = root / "vscode-extension"
            extension.mkdir()
            (extension / "package.json").write_text(
                json.dumps({"name": "agent-hub-vscode", "version": "0.0.2"}),
                encoding="utf-8",
            )
            old_vsix = extension / "agent-hub-vscode-0.0.1.vsix"
            current_vsix = extension / "agent-hub-vscode-0.0.2.vsix"
            old_vsix.write_text("old", encoding="utf-8")
            current_vsix.write_text("current", encoding="utf-8")

            artifacts = package_artifacts(root)

            self.assertIn(old_vsix, artifacts)
            self.assertNotIn(current_vsix, artifacts)


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
    (root / "release.json").write_text(
        json.dumps(
            {
                "extension_version": "0.1.0",
                "backend_version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    return root


if __name__ == "__main__":
    unittest.main()
