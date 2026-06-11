from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from agent_hub.application.diagnostics_service import BACKEND_FEATURES


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
        self.assertEqual(commands["agentHub.openDashboard"], "Agent Hub: Open Dashboard")
        self.assertEqual(commands["agentHub.runCheckup"], "Agent Hub: Run Checkup")
        self.assertEqual(commands["agentHub.enableFreeOnlyMode"], "Agent Hub: Use Free Models Only")
        self.assertEqual(commands["agentHub.enableTokenSafeMode"], "Agent Hub: Save Codex Tokens")
        self.assertEqual(commands["agentHub.enableCodexCliMode"], "Agent Hub: Use Signed-In Codex CLI")
        self.assertEqual(commands["agentHub.installCodexCli"], "Agent Hub: Install Codex CLI")
        self.assertEqual(commands["agentHub.installOllamaDesktop"], "Agent Hub: Install Ollama Desktop")
        self.assertEqual(commands["agentHub.checkHealth"], "Agent Hub: Check Health")
        self.assertEqual(commands["agentHub.checkRequirements"], "Agent Hub: Check Requirements")
        self.assertEqual(commands["agentHub.fixSafeConfig"], "Agent Hub: Repair Config")
        self.assertEqual(commands["agentHub.openRuntimeKernel"], "Agent Hub: Open Runtime Kernel")
        self.assertEqual(commands["agentHub.installPython"], "Agent Hub: Install Python")
        self.assertEqual(commands["agentHub.installNode"], "Agent Hub: Install Node.js")
        self.assertEqual(commands["agentHub.generateCommitMessage"], "Agent Hub: Generate Commit Message")
        self.assertEqual(commands["agentHub.autoSetupCline"], "Agent Hub: Auto-Configure Cline")
        self.assertEqual(commands["agentHub.setupCodingTool"], "Agent Hub: Set Up Coding Tool")
        self.assertEqual(commands["agentHub.setupCline"], "Agent Hub: Set Up Cline")
        self.assertEqual(commands["agentHub.copyClineConfig"], "Agent Hub: Copy Cline Config")
        self.assertEqual(commands["agentHub.testClineConnection"], "Agent Hub: Test Cline Connection")
        self.assertEqual(commands["agentHub.copyClaudeCodeConfig"], "Agent Hub: Copy Claude Code Config")
        self.assertEqual(commands["agentHub.testAnthropicEndpoint"], "Agent Hub: Test Anthropic Endpoint")
        self.assertEqual(commands["agentHub.openRouteLab"], "Agent Hub: Open Route Lab")

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

    def test_approval_mode_setting_is_safe_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        approval = package["contributes"]["configuration"]["properties"]["agentHub.approvalMode"]

        self.assertEqual(approval["default"], "safe")
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

    def test_sidebar_main_actions_have_inline_help_buttons(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("function sidebarActionHelp", source)
        self.assertIn('class="action-help"', source)
        self.assertIn(".action-help::after", sidebar)
        self.assertIn('id="helpToast"', sidebar)
        self.assertIn("function showHelpToast", sidebar)
        self.assertIn('helpToast.dataset.visible = "true"', sidebar)
        self.assertIn("wireStaticActionHelpButtons()", sidebar)
        self.assertIn("createActionHelpButton", sidebar)

        for label in [
            "Start",
            "Send",
            "Chat",
            "Dashboard",
            "Kernel",
            "Checkup",
            "Route Lab",
            "Models",
            "Benchmarks",
            "Save Codex Tokens",
            "Free Models Only",
            "Use Codex CLI",
            "Install Codex CLI",
            "Code",
            "Explain",
            "Run Checkup",
            "Check Requirements",
            "Repair Config",
            "Copy Cline Config",
            "Test Cline Connection",
            "Show Cline Setup",
        ]:
            self.assertIn(f'sidebarActionHelp("{label}"', sidebar)

    def test_sidebar_mode_buttons_toggle_and_show_running_state(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("function modeToggleState", source)
        self.assertIn("function dashboardModeLabel", source)
        self.assertIn("Mode: ${mode}", source)
        self.assertIn('id="headerCostMode"', sidebar)
        self.assertIn('id="heroCostMode"', sidebar)
        self.assertIn("repeat(auto-fit, minmax(74px, 1fr))", sidebar)
        self.assertIn("function dashboardCostMode", sidebar)
        self.assertIn("applyStandardCloudModeSettings", source)
        self.assertIn("modes.tokenSafeMode", source)
        self.assertIn("modes.freeOnlyStrictMode", source)
        self.assertIn("modes.codexCliMode", source)
        self.assertIn('class="command-button mode-toggle" id="quickTokenSafeMode"', sidebar)
        self.assertIn('class="command-button mode-toggle" id="quickFreeOnlyMode"', sidebar)
        self.assertIn('class="command-button mode-toggle" id="quickCodexCliMode"', sidebar)
        self.assertIn("renderModeToggles(dashboard)", sidebar)
        self.assertIn("Saving Codex Tokens", sidebar)
        self.assertIn("Adaptive fallback", sidebar)
        self.assertIn("micro/surgical/rescue", sidebar)
        self.assertIn("Free Models Only", sidebar)
        self.assertIn("Using Codex CLI", sidebar)
        self.assertIn("markButtonRunning", sidebar)
        self.assertIn('button[data-running="true"]', sidebar)
        self.assertIn('button.dataset.running = "true"', sidebar)
        self.assertIn('button.setAttribute("aria-busy", "true")', source)
        self.assertIn('button.removeAttribute("aria-busy")', source)
        self.assertIn("Stop Using Codex CLI", source)

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

    def test_sidebar_is_simple_first_with_advanced_details_collapsed(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        headings = [
            "<h2>What do you need?</h2>",
            "<h2>Boost Your Coding Agent</h2>",
            "<h2>Setup</h2>",
            "<h2>Advanced</h2>",
            "<h2>Tools</h2>",
            "<h2>Model Stats</h2>",
            "<h2>Runtime Kernel</h2>",
            "<h2>Orchestration</h2>",
            "<h2>Health</h2>",
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
        self.assertIn('<details class="advanced-shell">', source)
        self.assertIn("Fix a bug, explain a file, write tests, or make a small change", source)
        self.assertIn('class="task-preset"', source)
        self.assertIn("data-task-template", source)
        self.assertIn("function setQuickTaskText", source)
        self.assertIn("Fix bug", source)
        self.assertIn("Write tests", source)
        self.assertIn("Review code", source)
        self.assertIn("Refactor", source)
        self.assertIn("experience && experience.title", source)
        self.assertIn('setText(heroSummary, "Needs checkup")', source)
        self.assertIn('setText(heroSummary, "Start or send a task")', source)
        self.assertIn('class="topbar-chip hidden-telemetry" id="headerRoute"', source)
        self.assertIn('class="topbar-chip hidden-telemetry" id="headerCostMode"', source)
        self.assertIn('<span class="health-label">Status</span>', source)
        self.assertIn('id="quickTaskSend" type="submit" disabled>Send task</button>', source)
        self.assertIn("function currentSidebarState", source)
        self.assertIn("function updateQuickTaskState", source)
        self.assertIn("vscode.setState(currentSidebarState())", source)
        self.assertIn("quickTaskForm.requestSubmit()", source)
        self.assertIn("heroStatusText(stats, status)", source)
        self.assertIn("dashboard.experience", source)
        self.assertIn("experience_summary", source)
        self.assertIn("function experienceTone", source)
        self.assertIn('id="autoSetupCline"', source)
        self.assertIn("Auto-Configure Cline", source)
        self.assertIn('id="setupCodingTool"', source)
        self.assertIn("Copy + Test Tool", source)
        self.assertIn("Roo Code, Continue", source)
        self.assertIn("Provider: OpenAI Compatible", source)
        self.assertIn("Model: agent-hub-coding", source)
        self.assertIn('registerCommand("agentHub.autoSetupCline"', source)
        self.assertIn('registerCommand("agentHub.setupCodingTool"', source)
        self.assertIn('registerCommand("agentHub.setupCline"', source)
        self.assertIn('"autoSetupCline"', source)
        self.assertIn('"setupCodingTool"', source)
        self.assertIn("async function autoSetupCline", source)
        self.assertIn("async function ensureClineCliInstalled", source)
        self.assertIn("async function installClineCliWithNpm", source)
        self.assertIn("async function openClineCliInstallTerminalWithPermission", source)
        self.assertIn("function runClineAuthSetup", source)
        self.assertIn('"install", "-g", "cline"', source)
        self.assertIn("const cline = await clineCliStatus()", source)
        self.assertIn('label: "Cline"', source)
        self.assertIn('actionType: cline.installed ? "" : "autoSetupCline"', source)
        self.assertIn('"--provider"', source)
        self.assertIn('"--baseurl"', source)
        self.assertIn('"--modelid"', source)
        self.assertIn("Provider: OpenAI Compatible", source)
        self.assertIn("async function setupCodingTool", source)
        self.assertIn("async function setupCline", source)
        self.assertIn('id="connectClaudeCode"', source)
        self.assertIn("Connect Claude Code", source)
        self.assertIn('id="connectCodex"', source)
        self.assertIn("Connect Codex", source)
        self.assertIn('id="boostMyAgent"', source)
        self.assertIn("Boost My Agent", source)
        self.assertIn('postFromEvent("copyClaudeCodeConfig"', source)
        self.assertIn('postFromEvent("enableCodexCliMode"', source)
        self.assertIn('postFromEvent("enableTokenSafeMode"', source)
        self.assertIn('postFromEvent("autoSetupCline"', source)
        self.assertIn('postFromEvent("setupCodingTool"', source)
        self.assertNotIn("Gateway Control Plane", source)
        self.assertNotIn("Mission Control", source)
        self.assertIn("createStatusBarItem", source)
        self.assertIn('id="routingChain"', source)
        self.assertIn('id="routingSummaryGrid"', source)
        self.assertIn('id="routingReasonList"', source)
        self.assertIn('id="heroReadiness"', source)
        self.assertIn('id="quickDashboard"', source)
        self.assertIn('id="checkRequirements"', source)
        self.assertIn("function sidebarRoutingExplanation", source)
        self.assertIn("function renderRoutingIntelligence", source)
        self.assertIn("function readinessText", source)
        self.assertIn('id="onboardingList"', source)
        self.assertIn('id="contextDiagnostics"', source)
        self.assertIn('id="heroHealthScore"', source)
        self.assertIn('id="statsGrid"', source)
        self.assertIn("function dashboardHealthScore", source)
        self.assertIn("averageTokensPerCall", source)
        self.assertIn("health score", source)
        self.assertIn("readiness score", source)

    def test_advanced_commands_are_hidden_from_command_palette(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        command_palette = package["contributes"]["menus"]["commandPalette"]
        hidden = {
            item["command"]
            for item in command_palette
            if item.get("when") == "false"
        }

        for command in [
            "agentHub.openDashboard",
            "agentHub.openRuntimeKernel",
            "agentHub.checkRequirements",
            "agentHub.fixSafeConfig",
            "agentHub.enableTokenSafeMode",
            "agentHub.enableFreeOnlyMode",
            "agentHub.enableCodexCliMode",
            "agentHub.setupCline",
            "agentHub.copyClineConfig",
            "agentHub.openRouteLab",
            "agentHub.runPersonalBenchmark",
        ]:
            self.assertIn(command, hidden)

        for command in [
            "agentHub.chat",
            "agentHub.startServer",
            "agentHub.runCheckup",
            "agentHub.ask",
            "agentHub.codeAgent",
            "agentHub.research",
            "agentHub.explainFile",
            "agentHub.autoSetupCline",
            "agentHub.setupCodingTool",
        ]:
            self.assertNotIn(command, hidden)

    def test_first_run_does_not_auto_prompt_for_proofs(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        activate_start = source.index("function activate")
        activate_end = source.index("async function openAgentHubDashboard", activate_start)
        activate = source[activate_start:activate_end]

        self.assertNotIn("scheduleFirstRunProofPrompt(context)", activate)
        self.assertNotIn("showFirstRunProofPrompt(context)", activate)

    def test_runtime_kernel_is_visible_from_sidebar_and_command_palette(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("onCommand:agentHub.openRuntimeKernel", package["activationEvents"])
        self.assertIn('registerCommand("agentHub.openRuntimeKernel"', source)
        self.assertIn("/dashboard/kernel", source)
        self.assertIn("/v1/kernel", source)
        self.assertIn("function sidebarRuntimeKernel", source)
        self.assertIn("function renderRuntimeKernel", source)
        self.assertIn('id="quickKernel"', sidebar)
        self.assertIn('id="openRuntimeKernel"', sidebar)
        self.assertIn('id="kernelSignalGrid"', sidebar)
        self.assertIn('id="kernelActionList"', sidebar)
        self.assertIn('postFromEvent("openRuntimeKernel"', sidebar)

    def test_route_lab_is_visible_from_sidebar_and_command_palette(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("onCommand:agentHub.openRouteLab", package["activationEvents"])
        self.assertIn('registerCommand("agentHub.openRouteLab"', source)
        self.assertIn("function openRouteLabCommand", source)
        self.assertIn("function routeLabHtml", source)
        self.assertIn("named_baselines", source)
        self.assertIn("function formatRouteLabSavings", source)
        self.assertIn('"route-diagnose"', source)
        self.assertIn('id="quickRouteLab"', sidebar)
        self.assertIn('id="openRouteLab"', sidebar)
        self.assertIn('postFromEvent("openRouteLab"', sidebar)
        self.assertIn("/dashboard/routing-intelligence", source)

    def test_sidebar_shows_route_visualization_and_live_savings(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("function sidebarLiveSavings", source)
        self.assertIn("function sidebarRouteVisualization", source)
        self.assertIn("function renderLiveSavings", sidebar)
        self.assertIn("function renderRouteVisualization", sidebar)
        self.assertIn('id="liveSavingsGrid"', sidebar)
        self.assertIn('id="routeVisualization"', sidebar)
        self.assertIn("Live Savings", sidebar)
        self.assertIn("Route Decision", sidebar)
        self.assertIn("Cost Saved", source)
        self.assertIn("Fallbacks Prevented", source)
        self.assertIn("Context fit", source)
        self.assertIn("Reliability", source)

    def test_checkup_is_visible_from_sidebar_and_command_palette(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("onCommand:agentHub.runCheckup", package["activationEvents"])
        self.assertIn('registerCommand("agentHub.runCheckup"', source)
        self.assertIn("function runCheckupCommand", source)
        self.assertIn("promptForFixes: false", source)
        self.assertIn("fixSafeConfigCommand({ quietNoChange: true", source)
        self.assertIn('id="quickCheckup"', sidebar)
        self.assertIn('id="runCheckup"', sidebar)
        self.assertIn('postFromEvent("runCheckup"', sidebar)

    def test_sidebar_and_checkup_surface_runtime_usability(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("dashboard.runtimeUsability", source)
        self.assertIn("health.runtime_usability", source)
        self.assertIn("runtimeUsabilityScore", source)
        self.assertIn("runtime usability", source)
        self.assertIn("fetchRuntimeUsabilityForCheckup", source)
        self.assertIn("guideRuntimeUsabilityForCheckup", source)
        self.assertIn('"Choose Local Model"', source)
        self.assertIn('installOllamaDesktopCommand({ showAlreadyInstalled: false })', source)
        self.assertIn("await restartServer()", source)

    def test_safe_config_repair_is_visible_from_sidebar_and_command_palette(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        sidebar_start = source.index("function sidebarHtml")
        sidebar_end = source.index("function registerChatParticipant", sidebar_start)
        sidebar = source[sidebar_start:sidebar_end]

        self.assertIn("onCommand:agentHub.fixSafeConfig", package["activationEvents"])
        self.assertIn('registerCommand("agentHub.fixSafeConfig"', source)
        self.assertIn("function fixSafeConfigCommand", source)
        self.assertIn('"--fix-safe"', source)
        self.assertIn('id="fixSafeConfig"', sidebar)
        self.assertIn('postFromEvent("fixSafeConfig"', sidebar)

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

    def test_required_backend_features_cover_current_dashboard_endpoints(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        match = re.search(
            r"const REQUIRED_BACKEND_FEATURES = \[(?P<body>.*?)\];",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        required = set(re.findall(r'"([^"]+)"', match.group("body")))

        for feature in [
            "routing_intelligence_api",
            "routing_memory_api",
            "optimization_dashboard",
            "routing_simulation",
            "cost_dashboard",
            "model_leaderboard",
            "benchmark_results_dashboard",
            "workspace_checkpoints",
            "workspace_rollback_api",
            "events_endpoint",
            "dashboard_status_endpoints",
            "tool_execution_loop",
            "readiness_scorecard",
            "feature_maturity_status",
            "production_acceptance_check",
            "runtime_kernel_control_plane",
            "runtime_kernel_dashboard",
        ]:
            self.assertIn(feature, required)
            self.assertTrue(BACKEND_FEATURES[feature])

    def test_extension_test_script_runs_runtime_policy_tests(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        runtime_policy = EXTENSION_DIR / "runtime-policy.js"
        runtime_test = EXTENSION_DIR / "test" / "runtime-policy.test.js"

        self.assertIn("node --test test/*.test.js", package["scripts"]["test"])
        self.assertIn('require("./runtime-policy")', source)
        self.assertTrue(runtime_policy.exists())
        self.assertTrue(runtime_test.exists())

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
        self.assertIn("function generatedConfigStorageDir", source)
        self.assertIn("function applyGeneratedStoragePaths", source)
        self.assertIn("normalized === DEFAULT_CONFIG_FILENAME", source)
        self.assertIn('workspace_dir: normalizeWorkspaceDirOption(options.workspaceDir) || "."', source)
        self.assertIn('state_dir: storagePaths.stateDir', source)
        self.assertIn("const target = vscode.ConfigurationTarget.Global", source)
        self.assertIn("function clearWorkspaceAgentHubSettings", source)
        self.assertIn("Moved Agent Hub settings out of workspace settings.", source)

    def test_generated_config_defaults_are_cline_cloud_ready(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        helper_start = source.index("function generatedConfigApprovalMode")
        helper_end = source.index("function localConfigForLocalModels", helper_start)
        helper = source[helper_start:helper_end]
        config_start = source.index("function localConfigForLocalModels")
        config_end = source.index("function ollamaCloudModelAgentConfig", config_start)
        generated_config = source[config_start:config_end]
        repair_start = source.index("async function repairGeneratedLocalConfig")
        repair_end = source.index("function configsEquivalent", repair_start)
        repair = source[repair_start:repair_end]

        self.assertIn('return "auto";', helper)
        self.assertIn('return mode === "ask" ? "auto" : mode;', helper)
        self.assertIn("tool_loop_enabled_for_cline: false", generated_config)
        self.assertIn("approval_mode: generatedConfigApprovalMode(options.approvalMode)", generated_config)
        self.assertNotIn('approval_mode: "ask"', generated_config)
        self.assertIn("approvalMode: raw.approval_mode", repair)

    def test_config_repair_restarts_extension_owned_server(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        start_server_start = source.index("async function startServer")
        start_server_end = source.index("async function serverLaunchEnvironment", start_server_start)
        start_server = source[start_server_start:start_server_end]

        self.assertIn("configChanged && serverProcess", start_server)
        self.assertIn("restarting extension-owned backend", start_server)
        self.assertIn("Restarting Agent Hub to load repaired config", start_server)
        self.assertIn("Agent Hub config was repaired, but the running backend did not stop", start_server)

    def test_max_tokens_setting_is_unset_by_default(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.maxTokens"]
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIsNone(setting["default"])
        self.assertIn("null", setting["type"])
        self.assertIn("applyOptionalMaxTokens", source)
        self.assertNotIn("max_tokens: config.maxTokens", source)

    def test_automated_model_feedback_toggle_is_exposed(self) -> None:
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))
        setting = package["contributes"]["configuration"]["properties"]["agentHub.automatedModelFeedback"]
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertFalse(setting["default"])
        self.assertIn('id="autoFeedbackToggle"', source)
        self.assertIn('"toggleAutomatedFeedback"', source)
        self.assertIn("autoSubmitModelFeedback", source)
        self.assertIn("/v1/feedback", source)
        self.assertIn("agent-hub-research", source)

    def test_chat_settings_include_max_token_save_button(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))

        self.assertIn('id="maxTokenSave"', source)
        self.assertIn('id="freeOnlyModeSettings"', source)
        self.assertIn('id="quickFreeOnlyMode"', source)
        self.assertIn('id="freeOnlyMode"', source)
        self.assertIn(">Save Codex Tokens</button>", source)
        self.assertIn(">Free Models Only</button>", source)
        self.assertIn('id="quickTokenSafeMode"', source)
        self.assertIn('id="quickCodexCliMode"', source)
        self.assertIn('id="quickInstallCodexCli"', source)
        self.assertIn('id="quickBenchmarkReports"', source)
        self.assertIn(">Benchmarks</span>", source)
        self.assertIn('"openBenchmarkReportMenu"', source)
        self.assertIn('"runPersonalBenchmark"', source)
        self.assertIn('id="installOllamaDesktop"', source)
        self.assertIn('id="tokenSafeMode"', source)
        self.assertIn('"enableTokenSafeMode"', source)
        self.assertIn('"enableFreeOnlyMode"', source)
        self.assertIn('"enableCodexCliMode"', source)
        self.assertIn('"installCodexCli"', source)
        self.assertIn('"installOllamaDesktop"', source)
        self.assertIn("installOllamaDesktopCommand", source)
        self.assertIn("ollamaDesktopStatus", source)
        self.assertIn("OLLAMA_DOWNLOAD_URL", source)
        self.assertIn("enableTokenSafeModeCommand", source)
        self.assertIn("enableFreeOnlyModeCommand", source)
        self.assertIn("enableCodexCliModeCommand", source)
        self.assertIn("installCodexCliCommand", source)
        self.assertIn("codexCliStatus", source)
        self.assertIn("CODEX_CLI_NPM_PACKAGE", source)
        self.assertIn("@openai/codex@latest", source)
        self.assertIn("applyCodexCliModeSettings", source)
        self.assertIn("Use Codex CLI is on", source)
        self.assertIn('value="codex-cli"', source)
        self.assertIn("Signed-in Codex CLI", source)
        self.assertIn('id="modeSummary"', source)
        self.assertIn('id="settingsMessage" role="status" aria-live="polite"', source)
        self.assertIn("--cyan: #22d3ee;", source)
        self.assertIn('.mode-summary[data-mode="token-safe"]', source)
        self.assertIn("renderChatModeSummary", source)
        self.assertIn('button.setAttribute("aria-pressed"', source)
        self.assertIn("CODEX_CLI_CONTEXT_BUDGET", source)
        self.assertIn("DEFAULT_AGENT_CONTEXT_BUDGET", source)
        self.assertIn("isFreeCloudSavingsMode", source)
        self.assertIn('cloudRouteMode: "codex-cli"', source)
        self.assertIn("codexCliEnabled: true", source)
        self.assertIn("apiKeyModelsEnabled: false", source)
        self.assertIn("freeCloudPresetsEnabled: false", source)
        self.assertIn("codex_cli_token_optimized", source)
        self.assertIn('type: "enableMaxTokenSave"', source)
        self.assertIn("enableMaxTokenSaveModeFromWebview", source)
        self.assertIn("applyTokenSafeModeSettings", source)
        self.assertIn("applyFreeOnlyModeSettings", source)
        self.assertIn("Save Codex Tokens is on", source)
        self.assertIn("Free Models Only is on", source)
        self.assertIn("disableNonFreeModels: true", source)
        self.assertIn("disable_non_free_models", source)
        self.assertIn("applyStrictFreeOnlyModeToConfig", source)
        self.assertIn("strictFreeAgentConfigAllowed", source)
        self.assertIn("strictFreeSourceAllowed", source)
        self.assertIn("onCommand:agentHub.enableFreeOnlyMode", package["activationEvents"])
        self.assertIn("onCommand:agentHub.enableTokenSafeMode", package["activationEvents"])
        self.assertIn("onCommand:agentHub.enableCodexCliMode", package["activationEvents"])
        self.assertIn("onCommand:agentHub.installCodexCli", package["activationEvents"])
        self.assertIn("onCommand:agentHub.checkRequirements", package["activationEvents"])
        self.assertIn("onCommand:agentHub.installPython", package["activationEvents"])
        self.assertIn("onCommand:agentHub.installNode", package["activationEvents"])
        self.assertIn("token-safe", json.dumps(package["contributes"]["chatParticipants"]))
        self.assertIn("codex-cli", json.dumps(package["contributes"]["chatParticipants"]))
        self.assertIn("MAX_TOKEN_SAVE_OUTPUT_TOKENS", source)
        self.assertIn('agentProviderMode: "cloud"', source)
        self.assertIn('cloudRouteMode: "ollama-cloud"', source)
        self.assertIn("apiKeyModelsEnabled: true", source)
        self.assertIn("freeCloudPresetsEnabled: true", source)
        self.assertIn("freeOnly: false", source)
        self.assertIn("agentHubRequestOptions", source)
        self.assertIn("classification_text", source)
        self.assertIn("free_cloud_offload", source)
        self.assertIn("allow_cloud_exploration", source)
        self.assertIn('data.context_mode = "minimal"', source)
        self.assertIn("data.agent_context_compaction_enabled = true", source)
        self.assertIn("free_first: true", source)
        self.assertIn("simple_cloud_exploration_enabled: true", source)
        self.assertIn("free: source.free !== false", source)

    def test_save_codex_tokens_compacts_codex_fallback_budget(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        token_safe_start = source.index("async function applyTokenSafeModeSettings")
        token_safe_end = source.index("function normalizeChatSettingsInput", token_safe_start)
        token_safe_source = source[token_safe_start:token_safe_end]

        self.assertIn("maxTokens: CODEX_CLI_OUTPUT_TOKENS", token_safe_source)
        self.assertIn("agentMaxSteps: CODEX_CLI_AGENT_STEPS", token_safe_source)
        self.assertIn("codexCliEnabled: true", token_safe_source)
        self.assertIn("CODEX_CLI_CONTEXT_BUDGET", token_safe_source)
        self.assertIn("CODEX_CLI_MICRO_CONTEXT_BUDGET", source)
        self.assertIn("CODEX_CLI_RESCUE_CONTEXT_BUDGET", source)
        self.assertIn('config.update("contextMode", "minimal"', token_safe_source)
        self.assertIn("freeCloudSavingsMode: true", token_safe_source)
        self.assertIn("codexCliTokenOptimized: true", token_safe_source)
        self.assertIn('syncRunningBackendBoostMode("save_tokens")', token_safe_source)
        self.assertIn('syncRunningBackendBoostMode("balanced")', token_safe_source)
        self.assertIn("function applyTokenSafeRequestPlan", source)
        self.assertIn("function tokenSafeRequestPlan", source)
        self.assertIn("function activeRequestBoostMode", source)
        self.assertIn("function normalizeBoostMode", source)
        self.assertIn("function syncRunningBackendBoostMode", source)
        self.assertIn("context_chars: String(context || \"\").length", source)

        request_options_start = source.index("function agentHubRequestOptions")
        request_options_end = source.index("function normalizeServerUrl", request_options_start)
        request_options_source = source[request_options_start:request_options_end]
        free_branch = request_options_source[
            request_options_source.index("if (isFreeCloudSavingsMode(config))"):
            request_options_source.index("if (isCodexCliTokenOptimizedMode(config))")
        ]
        self.assertIn("const boostMode = activeRequestBoostMode(config)", request_options_source)
        self.assertIn("options.boost_mode = boostMode", request_options_source)
        self.assertIn('options.boost_mode = "save_tokens"', free_branch)
        self.assertIn('options.routing_mode = "cheapest"', free_branch)
        self.assertIn("options.free_cloud_offload = true", free_branch)
        self.assertIn("options.context_mode = \"minimal\"", free_branch)
        self.assertIn("options.minimal_tool_schema = true", free_branch)
        self.assertIn("options.reduced_repo_context = true", free_branch)
        self.assertIn("options.codex_cli_token_optimized = true", free_branch)
        self.assertIn('options.codex_cli_prompt_strategy = "task_context_digest"', free_branch)
        self.assertIn("options.token_safe_profile = plan.profile", free_branch)
        self.assertIn("options.token_safe_keywords = plan.keywords", free_branch)
        self.assertIn("options.max_context_tokens = plan.contextBudgetTokens", free_branch)
        self.assertIn("options.max_output_tokens = plan.outputTokens", free_branch)
        self.assertIn("options.max_tool_steps = plan.agentSteps", free_branch)
        self.assertIn("options.agent_max_steps = plan.agentSteps", free_branch)

        config_start = source.index("function applyMaxTokenSaveModeToConfig")
        config_end = source.index("function applyCodexCliModeToConfig", config_start)
        config_source = source[config_start:config_end]
        self.assertIn('data.boost_mode = "save_tokens"', config_source)
        self.assertIn('data.context_mode = "minimal"', config_source)
        self.assertIn("data.max_context_tokens = budget", config_source)
        self.assertIn("free_cloud_savings_mode: true", config_source)
        self.assertIn('max_tokens_mode: "explicit"', config_source)
        self.assertIn("minimal_tool_schema: true", config_source)
        self.assertIn("codex_cli_prompt_optimized: true", config_source)
        self.assertIn('data.boost_mode = "balanced"', source[source.index("function clearModeOptimizationFromConfig"):config_start])
        self.assertIn('boost_mode: options.cloudSettings?.maxTokenSaveMode ? "save_tokens" : "balanced"', source)

        cloud_sources_start = source.index("function cloudModelSources")
        cloud_sources_end = source.index("function freeCloudPresetSources", cloud_sources_start)
        cloud_sources_source = source[cloud_sources_start:cloud_sources_end]
        self.assertIn('free: settings.disableNonFreeModels === true ? false : routeMode === "codex-cli"', cloud_sources_source)
        self.assertIn('maxTokens: routeMode === "codex-cli" || settings.maxTokenSaveMode ? CODEX_CLI_OUTPUT_TOKENS : undefined', cloud_sources_source)

    def test_api_key_providers_auto_enable_only_when_key_exists(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("function availableApiKeyEnvs", source)
        self.assertIn("function syncApiKeyProviderAvailabilityForCurrentWorkspace", source)
        self.assertIn("function applyApiKeyProviderAvailability", source)
        self.assertIn("function sourceHasAvailableApiKey", source)
        self.assertIn("function isManagedApiKeyProviderAgent", source)
        self.assertIn("configSynced", source)
        self.assertIn("Enabled matching provider route entries.", source)

        cloud_sources_start = source.index("function cloudModelSources")
        cloud_sources_end = source.index("function ollamaCloudModelSources", cloud_sources_start)
        cloud_sources = source[cloud_sources_start:cloud_sources_end]

        self.assertIn("enabled: apiKeySourceEnabled(source, !!settings.apiKeyModelsEnabled, settings)", cloud_sources)
        self.assertIn("enabled: apiKeySourceEnabled(source, familyEnabled, settings)", cloud_sources)
        self.assertNotIn("enabled: !!settings.apiKeyModelsEnabled", cloud_sources)
        self.assertNotIn("const enabled = !!settings.freeCloudPresetsEnabled", cloud_sources)

        repair_start = source.index("async function repairGeneratedLocalConfig")
        repair_end = source.index("function configsEquivalent", repair_start)
        repair = source[repair_start:repair_end]
        self.assertIn("const keyEnvs = await availableApiKeyEnvs()", repair)
        self.assertIn("applyApiKeyProviderAvailability(raw, keyEnvs)", repair)
        self.assertIn("applyCloudRouteMode(raw, configCloudRouteMode(raw))", repair)

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

    def test_backend_cli_imports_without_site_packages_and_extension_probes_cli(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, "-S", "-c", "import agent_hub.cli; print('ready')"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ready")
        self.assertIn('"import agent_hub.cli"', source)

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
        self.assertIn("env.AGENT_HUB_API_TOKEN = config.apiToken", source)
        self.assertIn("config.approvalToken || runtimeApprovalToken", source)

    def test_fresh_machine_requirement_helpers_are_exposed(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
        package = json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))

        self.assertTrue((ROOT / "scripts" / "check-requirements.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "check-requirements.sh").exists())
        self.assertIn("onCommand:agentHub.checkRequirements", package["activationEvents"])
        self.assertIn("function checkRequirementsCommand", source)
        self.assertIn("function installPythonCommand", source)
        self.assertIn("function installNodeCommand", source)
        self.assertIn("function setupRequirementRows", source)
        self.assertIn('"installPython"', source)
        self.assertIn('"installNode"', source)
        self.assertIn("PYTHON_DOWNLOAD_URL", source)
        self.assertIn("NODE_DOWNLOAD_URL", source)


if __name__ == "__main__":
    unittest.main()
