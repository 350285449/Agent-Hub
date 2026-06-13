from __future__ import annotations

from pathlib import Path
import unittest

from scripts.fresh_machine_acceptance import run_acceptance


class FreshMachineAcceptanceTests(unittest.TestCase):
    def test_fresh_machine_acceptance_runs_without_local_models_or_api_keys(self) -> None:
        root = Path(__file__).resolve().parents[1]

        result = run_acceptance(root, use_current_python=True)

        self.assertTrue(result["ok"], result["failed"])
        check_ids = {check["id"] for check in result["checks"]}
        self.assertIn("init_ollama_default_model", check_ids)
        self.assertIn("server_health", check_ids)
        self.assertIn("route_request", check_ids)
        self.assertIn("production_check_cli", check_ids)
