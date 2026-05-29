from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "vscode-extension"


class VscodeExtensionContributionTests(unittest.TestCase):
    def test_activity_bar_and_sidebar_are_contributed(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        contributes = package["contributes"]

        self.assertIn("onView:agentHub.sidebar", package["activationEvents"])
        container = contributes["viewsContainers"]["activitybar"][0]
        self.assertEqual(container["id"], "agentHub")
        self.assertEqual(container["title"], "Agent Hub")

        view = contributes["views"]["agentHub"][0]
        self.assertEqual(view["id"], "agentHub.sidebar")
        self.assertEqual(view["type"], "webview")

    def test_sidebar_exposes_server_controls_as_commands(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        commands = {command["command"]: command["title"] for command in package["contributes"]["commands"]}

        self.assertEqual(commands["agentHub.startServer"], "Agent Hub: Start Server")
        self.assertEqual(commands["agentHub.stopServer"], "Agent Hub: Stop Server")
        self.assertEqual(commands["agentHub.restartServer"], "Agent Hub: Restart Server")
        self.assertEqual(commands["agentHub.openSettings"], "Agent Hub: Open Settings")
        self.assertEqual(commands["agentHub.checkHealth"], "Agent Hub: Check Health")
        self.assertEqual(commands["agentHub.copyClineConfig"], "Agent Hub: Copy Cline Config")
        self.assertEqual(commands["agentHub.testClineConnection"], "Agent Hub: Test Cline Connection")
        self.assertEqual(commands["agentHub.copyClaudeCodeConfig"], "Agent Hub: Copy Claude Code Config")
        self.assertEqual(commands["agentHub.testAnthropicEndpoint"], "Agent Hub: Test Anthropic Endpoint")

    def test_approval_mode_setting_is_ask_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        approval = package["contributes"]["configuration"]["properties"]["agentHub.approvalMode"]

        self.assertEqual(approval["default"], "ask")
        self.assertIn("safe", approval["enum"])
        self.assertIn("readonly", approval["enum"])
        self.assertIn("deny", approval["enum"])

    def test_start_server_is_primary_sidebar_action(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("registerWebviewViewProvider(SIDEBAR_VIEW_ID", source)
        self.assertIn("class PermissionManager", source)
        self.assertIn("requestPermission", source)
        start_index = source.index('id="startServer"')
        stop_index = source.index('id="stopServer"', start_index)
        restart_index = source.index('id="restartServer"', start_index)

        self.assertIn('data-primary-action="start-server"', source[start_index : start_index + 220])
        self.assertLess(start_index, stop_index)
        self.assertLess(start_index, restart_index)

    def test_sidebar_sections_match_platform_dashboard(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        headings = [
            "<h2>Control center</h2>",
            "<h2>Statistics</h2>",
            "<h2>Server</h2>",
            "<h2>Permissions</h2>",
            "<h2>Models / Providers</h2>",
            "<h2>Limits</h2>",
            "<h2>Token Usage</h2>",
            "<h2>Activity</h2>",
            "<h2>Logs</h2>",
            "<h2>Settings</h2>",
        ]
        positions = [source.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("createStatusBarItem", source)
        self.assertIn('id="routingChain"', source)
        self.assertIn('id="onboardingList"', source)
        self.assertIn('id="contextDiagnostics"', source)
        self.assertIn('id="heroHealthScore"', source)
        self.assertIn('id="statsGrid"', source)
        self.assertIn("function dashboardHealthScore", source)
        self.assertIn("averageTokensPerCall", source)
        self.assertIn("health score", source)

    def test_cline_compatibility_setting_is_enabled_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.clineCompatibilityMode"]

        self.assertTrue(setting["default"])

    def test_max_tokens_setting_is_unset_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.maxTokens"]
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIsNone(setting["default"])
        self.assertIn("null", setting["type"])
        self.assertIn("applyOptionalMaxTokens", source)
        self.assertNotIn("max_tokens: config.maxTokens", source)

    def test_extension_version_metadata_uses_package_json_source(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((EXTENSION_DIR / "package-lock.json").read_text(encoding="utf-8"))
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertEqual(lock["version"], package["version"])
        self.assertEqual(lock["packages"][""]["version"], package["version"])
        self.assertNotRegex(source, r"EXTENSION_VERSION\s*=\s*['\"][0-9]")
        self.assertIn("readExtensionPackageVersion", source)
        self.assertIn("package.json", source)

    def test_python_backend_version_is_separate_but_internally_consistent(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        backend_version = (ROOT / "agent_hub" / "version.py").read_text(encoding="utf-8")

        pyproject_version = pyproject.split('version = "', 1)[1].split('"', 1)[0]
        base_version = backend_version.split('BASE_VERSION = "', 1)[1].split('"', 1)[0]

        self.assertEqual(base_version, pyproject_version)

    def test_setup_helpers_are_registered_in_extension_source(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("function clineConfigText", source)
        self.assertIn("agent-hub-coding", source)
        self.assertIn("function claudeCodeConfigText", source)
        self.assertIn("/debug/request", source)


if __name__ == "__main__":
    unittest.main()
