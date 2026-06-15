from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .telemetry import research_dir


def compute_real_model_validation_status(config: Any | None = None) -> dict[str, Any]:
    if config is None:
        from ..config import load_config

        config = load_config()
    free_local = [
        {
            "agent": name,
            "provider": agent.provider,
            "model": agent.model,
            "base_url": agent.base_url,
        }
        for name, agent in sorted(config.agents.items())
        if agent.enabled and agent.free and agent.provider in {"openai-compatible", "local-research", "echo"}
    ]
    ollama_models = _ollama_models()
    configured_ollama = [
        row
        for row in free_local
        if row["base_url"] == "http://127.0.0.1:11434" and row["model"] in ollama_models
    ]
    available = bool(configured_ollama)
    return {
        "object": "agent_hub.research.real_model_validation_status",
        "real_model_subset_run": False,
        "available": available,
        "status": "available_not_run" if available else "not_available",
        "reason": "A configured free Ollama model is available, but this phase used deterministic local proof mode."
        if available
        else "No configured free/local Ollama model was confirmed available; deterministic local proof mode was used.",
        "configured_free_local_candidates": free_local,
        "ollama_models": sorted(ollama_models),
    }


def export_real_model_validation_status(state_dir: str | Path, config: Any | None = None) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_real_model_validation_status(config)
    json_path = directory / "real_model_validation.json"
    md_path = directory / "real_model_validation.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _ollama_models() -> set[str]:
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return set()
    models = payload.get("models") if isinstance(payload, dict) else []
    if not isinstance(models, list):
        return set()
    return {str(row.get("name") or "") for row in models if isinstance(row, dict) and row.get("name")}


def _markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Real Model Validation Status",
            "",
            f"- Status: {payload.get('status')}",
            f"- Real model subset run: {payload.get('real_model_subset_run')}",
            f"- Reason: {payload.get('reason')}",
            "",
        ]
    )


__all__ = ["compute_real_model_validation_status", "export_real_model_validation_status"]
