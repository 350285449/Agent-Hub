import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.research.gct_instrumentation import (
    GCTEventType,
    GCTRunRecorder,
    JsonlLedger,
    apply_pre_commit_intervention,
    calculate_gar,
    events_for_run,
    measure_commitment,
    panel_run_id,
    validate_pre_commit_interventions,
)
from agent_hub.research.gct_readiness import provider_diversity_gate
from scripts.frozen_panel_executor import ProviderBalancer, execute_row


class GCTInstrumentationTests(unittest.TestCase):
    def test_gar_uses_event_time_grounding_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = _row()
            run_id = panel_run_id(row["trial_id"], row["row_id"], 1)
            path = Path(tmp) / "events.jsonl"
            recorder = GCTRunRecorder(JsonlLedger(path), run_id=run_id, row=row)
            evidence = recorder.record(GCTEventType.EVIDENCE_DISCOVERY, evidence_unit="failure symptom")
            grounded = recorder.record(
                GCTEventType.BRANCH_CREATION,
                branch_id="a",
                evidence_refs=[evidence.event_id],
                local_grounding=1.0,
            )
            recorder.record(GCTEventType.BRANCH_SELECTION, selected_branch_id="a", evidence_refs=[grounded.event_id])
            recorder.record(GCTEventType.COMMITMENT, selected_branch_id="a", commitment_strength=0.9)

            gar = calculate_gar(events_for_run(path, run_id))

            self.assertEqual(gar["action_event_count"], 3)
            self.assertEqual(gar["local_grounding"][grounded.event_id], 1.0)
            self.assertLess(gar["post_commit_gar"], 1.0)

    def test_commitment_metrics_and_pre_commit_intervention_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = _row()
            run_id = panel_run_id(row["trial_id"], row["row_id"], 2)
            path = Path(tmp) / "events.jsonl"
            recorder = GCTRunRecorder(JsonlLedger(path), run_id=run_id, row=row)
            evidence = recorder.record(GCTEventType.EVIDENCE_DISCOVERY)
            apply_pre_commit_intervention(recorder, intervention_id="gate", prompt="check", evidence_refs=[evidence.event_id])
            recorder.record(GCTEventType.BRANCH_SELECTION, selected_branch_id="a", evidence_refs=[evidence.event_id])
            recorder.record(GCTEventType.BRANCH_SWITCHING, previous_branch_id="a", selected_branch_id="b", evidence_refs=[evidence.event_id])
            recorder.record(
                GCTEventType.COMMITMENT,
                selected_branch_id="b",
                evidence_refs=[evidence.event_id],
                commitment_strength=0.82,
            )

            events = events_for_run(path, run_id)
            commitment = measure_commitment(events)
            intervention = validate_pre_commit_interventions(events)

            self.assertEqual(commitment["first_branch_choice"], "a")
            self.assertEqual(commitment["branch_reversals"], 1)
            self.assertTrue(commitment["lock_in"])
            self.assertTrue(intervention["valid"])
            with self.assertRaises(RuntimeError):
                apply_pre_commit_intervention(recorder, intervention_id="late", prompt="too late")

    def test_frozen_panel_dry_run_writes_required_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = _row()
            result = execute_row(row, output_dir=Path(tmp), router=None, dry_run=True)

            self.assertTrue(result["valid_instrumentation"])
            for key in ("events_path", "raw_trace_path", "gar_path", "commitment_metrics_path", "outcome_metrics_path"):
                self.assertTrue(Path(result[key]).exists())
            events = [json.loads(line) for line in Path(result["events_path"]).read_text(encoding="utf-8").splitlines()]
            event_types = {event["event_type"] for event in events}
            self.assertIn("evidence_discovery", event_types)
            self.assertIn("commitment_event", event_types)

    def test_provider_diversity_gate_rejects_single_family_dominance(self) -> None:
        rows = [
            {
                "status": "completed",
                "valid_instrumentation": True,
                "malformed_output_accepted": False,
                "provider_calls": [
                    {"agent": "ollama-gemma-cloud", "model": "gemma4:31b-cloud", "valid_structured_output": True}
                ],
            }
            for _ in range(4)
        ]

        gate = provider_diversity_gate(rows, expected_rows=4, min_model_families=3)

        self.assertFalse(gate["passed"])
        self.assertIn("gemma", gate["family_counts"])
        self.assertTrue(any("exceeds share cap" in blocker for blocker in gate["blockers"]))

    def test_provider_balancer_prefers_underused_approved_family(self) -> None:
        agents = {
            "ollama-gemma-cloud": _agent("ollama-gemma-cloud", "gemma4:31b-cloud"),
            "ollama-qwen-cloud": _agent("ollama-qwen-cloud", "qwen3.5:cloud"),
            "ollama-kimi-cloud": _agent("ollama-kimi-cloud", "kimi-k2.6:cloud"),
        }
        balancer = ProviderBalancer(
            agents,
            approved_routes=list(agents),
            max_family_share=0.5,
            min_model_families=3,
            expected_rows=50,
        )
        balancer.observe_result(
            {
                "status": "completed",
                "valid_instrumentation": True,
                "provider_calls": [
                    {"agent": "ollama-gemma-cloud", "model": "gemma4:31b-cloud", "valid_structured_output": True}
                ],
            }
        )

        route = balancer.route_order()

        self.assertNotEqual(route[0], "ollama-gemma-cloud")


def _row() -> dict:
    return {
        "trial_id": "trial",
        "row_id": "row-1",
        "assigned_arm": "treatment",
        "prompt": "Diagnose the failure and define a verifier.",
        "evidence_units_required": ["failure symptom", "branch comparison", "verifier condition"],
    }


class _agent:
    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.model = model
