from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.application import AdaptiveApplicationService
from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest
from agent_hub.repository_intelligence import RepositoryIntelligenceStore


class RepositoryIntelligenceTests(unittest.TestCase):
    def test_repository_dna_detects_minecraft_mod_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minecraft_mod(root)
            store = RepositoryIntelligenceStore(root, root / "state")

            dna = store.repository_dna()
            memory = store.workspace_memory()

        self.assertEqual(dna.project, "Minecraft Mod")
        self.assertEqual(dna.language, "java")
        self.assertEqual(dna.architecture, "Event Driven")
        self.assertIn("fabric", dna.frameworks)
        self.assertIn("Networking", dna.risk_areas)
        self.assertIn("Serialization", dna.risk_areas)
        self.assertTrue(memory["facts"])

    def test_repository_dna_changes_routing_for_repo_specific_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minecraft_mod(root)
            config = _repo_routing_config(root)
            decision = AgentRouter(config).decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Implement packet serialization in src/Main.java"}],
                )
            )

        self.assertEqual(decision.selected_agent, "claude")
        self.assertEqual(decision.repository_dna["project"], "Minecraft Mod")
        self.assertTrue(decision.failure_prediction["chance_of_success"] > 0)
        self.assertTrue(decision.candidate_scores[0]["repository_dna"]["active"])

    def test_repository_dna_does_not_backfill_framework_across_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minecraft_mod(root)
            classification = AgentRouter(_repo_routing_config(root))._classify_request(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "Explain src/app.ts"}],
                )
            )

        self.assertEqual(classification.language, "typescript")
        self.assertEqual(classification.framework, "unknown")

    def test_routing_simulation_exposes_killer_feature_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minecraft_mod(root)
            config = _repo_routing_config(root)
            router = AgentRouter(config)
            service = AdaptiveApplicationService(
                config,
                router=router,
                agent_runner=_UnusedRunner(),
                team_agent_runner=_UnusedRunner(),
                workflow_engine=_UnusedRunner(),
            )

            simulation = service.simulate_request(
                HubRequest(
                    session_id="sim",
                    messages=[{"role": "user", "content": "large architecture migration for networking"}],
                )
            )

        self.assertEqual(simulation["object"], "agent_hub.routing_simulation")
        self.assertEqual(simulation["repository_dna"]["project"], "Minecraft Mod")
        self.assertIn("chance_of_success", simulation["failure_prediction"])
        self.assertIn("multi_agent_debate", simulation)
        self.assertIn("auto_repair_loop", simulation)
        self.assertIn("cost_optimizer", simulation)
        self.assertIn("workspace_memory", simulation)
        self.assertIn("model_performance_database", simulation)
        self.assertIn("autonomous_night_mode", simulation)
        self.assertIn("ai_team_visualization", simulation)


class _UnusedRunner:
    def run(self, *args, **kwargs):  # pragma: no cover - simulation does not execute providers
        raise AssertionError("runner should not be used")

    def execute(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("workflow should not be used")


def _repo_routing_config(root: Path) -> HubConfig:
    return HubConfig(
        workspace_dir=root,
        state_dir=root / "state",
        free_only=False,
        repo_context_enabled=False,
        adaptive_learning_enabled=False,
        default_route=["gpt", "claude", "deepseek", "gemini"],
        agents={
            "gpt": AgentConfig(
                name="gpt",
                provider="openai",
                model="gpt-test",
                coding_score=0.5,
                reasoning_score=0.5,
            ),
            "claude": AgentConfig(
                name="claude",
                provider="anthropic",
                model="claude-test",
                coding_score=0.5,
                reasoning_score=0.5,
            ),
            "deepseek": AgentConfig(
                name="deepseek",
                provider="openai-compatible",
                provider_type="deepseek",
                model="deepseek-test",
                coding_score=0.5,
                reasoning_score=0.5,
            ),
            "gemini": AgentConfig(
                name="gemini",
                provider="gemini",
                model="gemini-test",
                coding_score=0.5,
                reasoning_score=0.5,
            ),
        },
    )


def _write_minecraft_mod(root: Path) -> None:
    (root / "src" / "main" / "java" / "example").mkdir(parents=True)
    (root / "build.gradle").write_text(
        "\n".join(
            [
                "plugins { id 'fabric-loom' version '1.7-SNAPSHOT' }",
                "dependencies {",
                "  implementation 'net.fabricmc:fabric-loader:0.15.0'",
                "  implementation 'net.fabricmc.fabric-api:fabric-api:0.92.0'",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (root / "fabric.mod.json").write_text('{"schemaVersion":1,"id":"example"}', encoding="utf-8")
    (root / "src" / "main" / "java" / "example" / "Main.java").write_text(
        "\n".join(
            [
                "package example;",
                "public final class Main {",
                "  public void onInitialize() {",
                "    // Event callback touches networking and json serialization.",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
