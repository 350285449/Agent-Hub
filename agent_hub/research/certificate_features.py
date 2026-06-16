from __future__ import annotations

from typing import Any


_CERTIFICATE_BY_CATEGORY = {
    "testing": 0.95,
    "bug_fix": 0.75,
    "code_generation": 0.7,
    "refactor": 0.65,
    "documentation": 0.55,
    "architecture": 0.45,
    "analysis": 0.35,
}

_EXECUTABILITY_BY_CATEGORY = {
    "testing": 0.9,
    "bug_fix": 0.82,
    "code_generation": 0.78,
    "refactor": 0.72,
    "documentation": 0.45,
    "architecture": 0.4,
    "analysis": 0.35,
}

_REPOSITORY_EXECUTABILITY = {
    "Agent-Hub": 0.85,
    "ytdl_site": 0.7,
    "face": 0.58,
}


def infer_certificate_features(row: dict[str, Any]) -> dict[str, float]:
    """Infer pre-run verifiability features from task and context metadata only."""
    category = str(row.get("category") or row.get("task_type") or "")
    repository = str(row.get("repository") or "")
    selected_files = [str(item).lower() for item in row.get("selected_files") or row.get("context_files") or []]
    context_budget = _clamp(float(row.get("context_budget", row.get("context budget", 0)) or 0) / 100.0)
    context_tokens = _clamp(float(row.get("context_tokens", row.get("context_token_count", 0)) or 0) / 12_000.0)
    text = " ".join([str(row.get("task") or row.get("task_id") or ""), category, repository, *selected_files]).lower()

    has_tests = any("test" in path or "spec" in path or "fixture" in path for path in selected_files)
    has_lock_or_manifest = any(path.endswith(("package-lock.json", "uv.lock", "poetry.lock", "pyproject.toml", "package.json")) for path in selected_files)
    has_proof_surface = any(marker in text for marker in ("proof", "verify", "verification", "benchmark", "signature", "hash", "checksum", "certificate"))
    has_docs_only = category in {"documentation", "architecture", "analysis"} and not has_tests

    certificate_strength = _CERTIFICATE_BY_CATEGORY.get(category, 0.5)
    certificate_strength += 0.08 if has_tests else 0.0
    certificate_strength += 0.05 if has_lock_or_manifest else 0.0
    certificate_strength += 0.04 * context_budget
    if has_docs_only:
        certificate_strength -= 0.06

    environment_executability = 0.55 * _EXECUTABILITY_BY_CATEGORY.get(category, 0.5) + 0.45 * _REPOSITORY_EXECUTABILITY.get(repository, 0.55)
    environment_executability += 0.08 if has_tests else 0.0
    environment_executability += 0.05 if has_lock_or_manifest else 0.0
    environment_executability += 0.05 * min(context_budget, context_tokens)

    verification_cost = {
        "testing": 0.55,
        "bug_fix": 0.6,
        "code_generation": 0.72,
        "refactor": 0.78,
        "documentation": 0.35,
        "architecture": 0.5,
        "analysis": 0.45,
    }.get(category, 0.5)
    verification_cost += 0.12 if repository == "Agent-Hub" else 0.0
    verification_cost += 0.08 * context_budget
    verification_cost -= 0.08 if has_tests else 0.0

    cryptographic_certificate = 1.0 if any(marker in text for marker in ("signature", "hash", "checksum", "signed", "cryptographic")) else 0.0
    if not cryptographic_certificate and has_proof_surface:
        cryptographic_certificate = 0.35

    return {
        "certificate_strength": round(_clamp(certificate_strength), 6),
        "environment_executability": round(_clamp(environment_executability), 6),
        "verification_cost": round(_clamp(verification_cost), 6),
        "cryptographic_certificate": round(_clamp(cryptographic_certificate), 6),
    }


def certificate_score(row: dict[str, Any]) -> float:
    features = infer_certificate_features(row)
    score = (
        0.34 * features["certificate_strength"]
        + 0.34 * features["environment_executability"]
        + 0.18 * (1.0 - features["verification_cost"])
        + 0.14 * features["cryptographic_certificate"]
    )
    return round(_clamp(score), 6)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = ["certificate_score", "infer_certificate_features"]
