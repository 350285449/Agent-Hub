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
        self.assertEqual(commands["agentHub.generateCommitMessage"], "Agent Hub: Generate Commit Message")
        self.assertEqual(commands["agentHub.copyClineConfig"], "Agent Hub: Copy Cline Config")
        self.assertEqual(commands["agentHub.testClineConnection"], "Agent Hub: Test Cline Connection")
        self.assertEqual(commands["agentHub.copyClaudeCodeConfig"], "Agent Hub: Copy Claude Code Config")
        self.assertEqual(commands["agentHub.testAnthropicEndpoint"], "Agent Hub: Test Anthropic Endpoint")

    def test_commit_message_generator_is_contributed_to_scm(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("onCommand:agentHub.generateCommitMessage", package["activationEvents"])
        scm_menu = package["contributes"]["menus"]["scm/title"]
        self.assertTrue(
            any(item["command"] == "agentHub.generateCommitMessage" for item in scm_menu)
        )
        scm_input_menu = package["contributes"]["menus"]["scm/inputBox"]
        self.assertTrue(
            any(item["command"] == "agentHub.generateCommitMessage" for item in scm_input_menu)
        )
        self.assertIn('registerCommand("agentHub.generateCommitMessage"', source)
        self.assertIn("function generateCommitMessage", source)
        self.assertIn("repository.inputBox.value = message", source)

    def test_approval_mode_setting_is_ask_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        approval = package["contributes"]["configuration"]["properties"]["agentHub.approvalMode"]

        self.assertEqual(approval["default"], "ask")
        self.assertIn("safe", approval["enum"])
        self.assertIn("readonly", approval["enum"])
        self.assertIn("deny", approval["enum"])

    def test_sidebar_has_single_prominent_server_action(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("registerWebviewViewProvider(SIDEBAR_VIEW_ID", source)
        self.assertIn("class PermissionManager", source)
        self.assertIn("requestPermission", source)
        self.assertEqual(sidebar.count('data-primary-action="start-server"'), 1)
        self.assertIn('id="heroServerAction"', sidebar)
        self.assertIn(">Start</button>", sidebar)
        self.assertIn('.hero-server-action[data-state="Running"]', sidebar)
        self.assertIn("background: var(--ok);", sidebar)
        self.assertNotIn('id="startServer"', sidebar)

    def test_sidebar_title_bar_avoids_crowded_server_buttons(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        view_title = package["contributes"]["menus"].get("view/title", [])

        sidebar_commands = {
            item["command"]
            for item in view_title
            if item.get("when") == "view == agentHub.sidebar"
        }
        self.assertNotIn("agentHub.startServer", sidebar_commands)
        self.assertNotIn("agentHub.checkHealth", sidebar_commands)
        self.assertNotIn("agentHub.openSettings", sidebar_commands)

    def test_sidebar_sections_match_platform_dashboard(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        headings = [
            "<h2>Ask anything</h2>",
            "<h2>Health</h2>",
            "<h2>Setup</h2>",
            "<h2>Permissions</h2>",
            "<h2>Models</h2>",
            "<h2>Routing Intelligence</h2>",
            "<h2>Limits</h2>",
            "<h2>Tokens</h2>",
            "<h2>Recent Activity</h2>",
            "<h2>Logs</h2>",
            "<h2>Settings</h2>",
        ]
        positions = [source.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("createStatusBarItem", source)
        self.assertIn('id="routingChain"', source)
        self.assertIn('id="routingSummaryGrid"', source)
        self.assertIn('id="routingReasonList"', source)
        self.assertIn("function sidebarRoutingExplanation", source)
        self.assertIn("function renderRoutingIntelligence", source)
        self.assertIn('id="onboardingList"', source)
        self.assertIn('id="contextDiagnostics"', source)
        self.assertIn('id="heroHealthScore"', source)
        self.assertIn('id="statsGrid"', source)
        self.assertIn("function dashboardHealthScore", source)
        self.assertIn("averageTokensPerCall", source)
        self.assertIn("health score", source)

    def test_webview_theme_tokens_have_dark_mode_fallbacks(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("--app-fg: var(--vscode-sideBar-foreground, var(--vscode-foreground, #d4d4d4))", source)
        self.assertIn("--app-bg: var(--vscode-editor-background, var(--vscode-sideBar-background, #1f2328))", source)
        self.assertIn("color: var(--app-fg);", source)
        self.assertIn("--input-fg: var(--vscode-input-foreground, var(--app-fg))", source)

    def test_lm_studio_offline_polling_is_quiet(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("function isLocalServerOfflineError", source)
        self.assertIn("if (!isLocalServerOfflineError(error))", source)
        self.assertIn('return "server is not running";', source)

    def test_cline_compatibility_setting_is_enabled_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.clineCompatibilityMode"]

        self.assertTrue(setting["default"])

    def test_extension_config_defaults_to_global_storage(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.configPath"]
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertEqual(setting["default"], "")
        self.assertIn("globalStorageUri", source)
        self.assertIn("function defaultExtensionConfigPath", source)
        self.assertIn("function workspaceStorageKey", source)
        self.assertIn("normalized === DEFAULT_CONFIG_FILENAME", source)
        self.assertIn('workspace_dir: normalizeWorkspaceDirOption(options.workspaceDir) || "."', source)
        self.assertIn("const target = vscode.ConfigurationTarget.Global", source)
        self.assertIn("function clearWorkspaceAgentHubSettings", source)
        self.assertIn("Moved Agent Hub settings out of workspace settings.", source)

    def test_max_tokens_setting_is_unset_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.maxTokens"]
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIsNone(setting["default"])
        self.assertIn("null", setting["type"])
        self.assertIn("applyOptionalMaxTokens", source)
        self.assertNotIn("max_tokens: config.maxTokens", source)

    def test_chat_settings_include_max_token_save_button(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn('id="maxTokenSave"', source)
        self.assertIn('type: "enableMaxTokenSave"', source)
        self.assertIn("enableMaxTokenSaveModeFromWebview", source)
        self.assertIn("MAX_TOKEN_SAVE_CONTEXT_BUDGET", source)
        self.assertIn('agentProviderMode: "cloud"', source)
        self.assertIn('cloudRouteMode: "ollama-cloud"', source)
        self.assertIn("apiKeyModelsEnabled: false", source)
        self.assertIn('data.context_mode = "minimal"', source)
        self.assertIn("data.agent_context_compaction_enabled = true", source)

    def test_commit_message_generation_keeps_small_output_cap(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        helper_start = source.index("function applyOptionalMaxTokens")
        helper_end = source.index("function normalizeServerUrl", helper_start)
        helper = source[helper_start:helper_end]
        commit_start = source.index("async function requestCommitMessage")
        commit_end = source.index("function commitMessageTask", commit_start)
        commit_source = source[commit_start:commit_end]

        self.assertIn("max_tokens: 160", commit_source)
        self.assertIn("applyOptionalMaxTokens(body, config)", commit_source)
        self.assertLess(helper.index("body.max_tokens"), helper.index("config.maxTokens"))
        self.assertIn("return body;", helper[: helper.index("config.maxTokens")])

    def test_extension_version_metadata_uses_package_json_source(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((EXTENSION_DIR / "package-lock.json").read_text(encoding="utf-8"))
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertEqual(lock["version"], package["version"])
        self.assertEqual(lock["packages"][""]["version"], package["version"])
        self.assertNotRegex(source, r"EXTENSION_VERSION\s*=\s*['\"][0-9]")
        self.assertIn("readExtensionPackageVersion", source)
        self.assertIn("package.json", source)
        self.assertIn('env.PYTHONSAFEPATH = "1"', source)
        self.assertIn('env.PYTHONDONTWRITEBYTECODE = "1"', source)

    def test_extension_and_python_backend_versions_match(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        backend_version = (ROOT / "agent_hub" / "version.py").read_text(encoding="utf-8")

        pyproject_version = pyproject.split('version = "', 1)[1].split('"', 1)[0]
        base_version = backend_version.split('BASE_VERSION = "', 1)[1].split('"', 1)[0]

        self.assertEqual(base_version, pyproject_version)
        self.assertEqual(package["version"], pyproject_version)

    def test_setup_helpers_are_registered_in_extension_source(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("function clineConfigText", source)
        self.assertIn("agent-hub-coding", source)
        self.assertIn("function claudeCodeConfigText", source)
        self.assertIn("/debug/request", source)


if __name__ == "__main__":
    unittest.main()
