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

    def test_start_server_is_primary_sidebar_action(self) -> None:
        source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

        self.assertIn("registerWebviewViewProvider(SIDEBAR_VIEW_ID", source)
        start_index = source.index('id="startServer"')
        stop_index = source.index('id="stopServer"', start_index)
        restart_index = source.index('id="restartServer"', start_index)

        self.assertIn('data-primary-action="start-server"', source[start_index : start_index + 220])
        self.assertLess(start_index, stop_index)
        self.assertLess(start_index, restart_index)


if __name__ == "__main__":
    unittest.main()
