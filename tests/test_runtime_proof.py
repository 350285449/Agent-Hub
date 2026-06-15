from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.proof_runtime import (
    format_runtime_proof_report,
    proof_config,
    runtime_proof_report,
    write_runtime_proof_report,
)


class RuntimeProofTests(unittest.TestCase):
    def test_runtime_proof_report_covers_release_gate_checks(self) -> None:
        report = runtime_proof_report(
            proof_config(),
            route="cloud-agent",
            full=True,
            root=Path.cwd(),
            benchmark_report={
                "object": "agent_hub.benchmark_proof",
                "task_count": 1,
                "dataset": {"name": "proof-full", "fingerprint": "abc"},
                "comparison": {"cost_reduction": 10.0, "success_delta": 0.0},
            },
        )

        checks = {check["id"]: check for check in report["checks"]}
        self.assertEqual(report["object"], "agent_hub.release_proof")
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "full")
        self.assertTrue(
            {
                "backend_startup",
                "diagnostics",
                "provider_availability",
                "routing",
                "agent_execution",
                "patching_rollback",
                "extension_connectivity",
                "plugin_safety",
                "architecture_guardrails",
                "benchmark_validation",
            }.issubset(checks)
        )
        self.assertFalse(checks["architecture_guardrails"]["required"])
        self.assertEqual(report["benchmark"]["dataset"], "proof-full")
        self.assertFalse(report["ci_gate"]["release_blocking"])

    def test_runtime_proof_report_is_machine_writable_and_human_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = runtime_proof_report(proof_config(), route="cloud-agent", root=Path.cwd())
            target = write_runtime_proof_report(report, Path(tmp) / "release-proof.json")
            saved = json.loads(target.read_text(encoding="utf-8"))
            text = format_runtime_proof_report(report)

        self.assertEqual(saved["object"], "agent_hub.release_proof")
        self.assertIn("Agent-Hub release proof", text)
        self.assertIn("backend_startup", text)


if __name__ == "__main__":
    unittest.main()
