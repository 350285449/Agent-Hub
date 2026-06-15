from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_hub.research.real_model_validation import compute_real_model_validation_status, export_real_model_validation_status


@dataclass
class _Agent:
    provider: str
    model: str
    base_url: str
    enabled: bool = True
    free: bool = True


@dataclass
class _Config:
    agents: dict[str, _Agent]


def test_real_model_validation_status_exports_without_model_call(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    config = _Config(agents={"echo": _Agent("echo", "local-echo", "")})

    payload = compute_real_model_validation_status(config)
    paths = export_real_model_validation_status(state, config)

    assert payload["real_model_subset_run"] is False
    assert payload["configured_free_local_candidates"][0]["agent"] == "echo"
    assert Path(paths["json"]).exists()
