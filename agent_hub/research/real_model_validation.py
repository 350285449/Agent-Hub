from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from .telemetry import research_dir


VALIDATION_PROMPTS = (
    {
        "task_id": "real-local-coding-001",
        "task_type": "coding",
        "prompt": "Write a concise plan to fix a failing Python unit test. Include the words test and fix.",
        "expected_keywords": ["test", "fix"],
    },
    {
        "task_id": "real-local-routing-001",
        "task_type": "reasoning",
        "prompt": "Explain why a fallback router should track provider health. Include health and fallback.",
        "expected_keywords": ["health", "fallback"],
    },
    {
        "task_id": "real-local-summary-001",
        "task_type": "summarization",
        "prompt": "Summarize why secrets should be redacted before provider calls. Include secret and provider.",
        "expected_keywords": ["secret", "provider"],
    },
)


@dataclass(frozen=True, slots=True)
class LocalModelCandidate:
    agent: str
    model: str
    base_url: str


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
    configured_ollama = _configured_ollama_candidates(free_local, ollama_models)
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
        "configured_available_ollama_models": configured_ollama,
        "ollama_models": sorted(ollama_models),
    }


def run_real_model_validation_subset(state_dir: str | Path, config: Any | None = None) -> dict[str, Any]:
    status = compute_real_model_validation_status(config)
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    results_path = directory / "real_model_validation_results.jsonl"
    candidates = status.get("configured_available_ollama_models") if isinstance(status.get("configured_available_ollama_models"), list) else []
    if not candidates:
        results_path.touch(exist_ok=True)
        payload = {
            **status,
            "object": "agent_hub.research.real_model_validation_run",
            "real_model_subset_run": False,
            "status": "not_available",
            "results": [],
            "results_path": str(results_path),
        }
        _write_validation_outputs(directory, payload)
        return payload

    candidate = LocalModelCandidate(
        agent=str(candidates[0]["agent"]),
        model=str(candidates[0]["model"]),
        base_url=str(candidates[0]["base_url"]),
    )
    rows = [_run_prompt(candidate, prompt) for prompt in VALIDATION_PROMPTS]
    with results_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    payload = {
        **status,
        "object": "agent_hub.research.real_model_validation_run",
        "real_model_subset_run": True,
        "status": "completed",
        "selected_agent": candidate.agent,
        "selected_model": candidate.model,
        "results": rows,
        "success_rate": round(sum(1 for row in rows if row["success"]) / len(rows), 6) if rows else 0.0,
        "average_validation_score": round(sum(float(row["validation_score"]) for row in rows) / len(rows), 6) if rows else 0.0,
        "results_path": str(results_path),
    }
    _write_validation_outputs(directory, payload)
    return payload


def export_real_model_validation_status(state_dir: str | Path, config: Any | None = None) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = run_real_model_validation_subset(state_dir, config)
    json_path, md_path = _write_validation_outputs(directory, payload)
    return {"json": str(json_path), "markdown": str(md_path)}


def _configured_ollama_candidates(free_local: list[dict[str, Any]], ollama_models: set[str]) -> list[dict[str, str]]:
    return [
        {
            "agent": str(row["agent"]),
            "model": str(row["model"]),
            "base_url": str(row["base_url"]),
        }
        for row in free_local
        if row["base_url"] == "http://127.0.0.1:11434" and row["model"] in ollama_models
    ]


def _run_prompt(candidate: LocalModelCandidate, prompt: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    error = ""
    text = ""
    try:
        text = _ollama_generate(candidate, str(prompt["prompt"]))
    except Exception as exc:  # provider validation must never break analysis
        error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    expected = [str(item).lower() for item in prompt.get("expected_keywords", [])]
    lowered = text.lower()
    keyword_score = sum(1 for word in expected if word in lowered) / max(1, len(expected))
    validation_score = round(keyword_score, 6) if text else 0.0
    return {
        "task_id": prompt["task_id"],
        "task_type": prompt["task_type"],
        "selected_agent": candidate.agent,
        "selected_model": candidate.model,
        "provider": "ollama",
        "latency_ms": latency_ms,
        "validation_score": validation_score,
        "success": validation_score >= 0.5,
        "error": error,
        "output_preview": text[:500],
    }


def _ollama_generate(candidate: LocalModelCandidate, prompt: str) -> str:
    url = candidate.base_url.rstrip("/") + "/api/generate"
    body = json.dumps({"model": candidate.model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload.get("response") or "")


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
    lines = [
        "# Real Model Validation Status",
        "",
        f"- Status: {payload.get('status')}",
        f"- Real model subset run: {payload.get('real_model_subset_run')}",
        f"- Reason: {payload.get('reason')}",
    ]
    if payload.get("real_model_subset_run"):
        lines.extend(
            [
                f"- Selected model: {payload.get('selected_model')}",
                f"- Success rate: {payload.get('success_rate')}",
                f"- Average validation score: {payload.get('average_validation_score')}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _write_validation_outputs(directory: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_path = directory / "real_model_validation.json"
    md_path = directory / "real_model_validation.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return json_path, md_path


__all__ = [
    "compute_real_model_validation_status",
    "export_real_model_validation_status",
    "run_real_model_validation_subset",
]
