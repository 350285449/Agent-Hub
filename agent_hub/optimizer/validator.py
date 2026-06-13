from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationGate:
    name: str
    required: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "description": self.description,
        }


QUALITY_GATES: dict[str, list[ValidationGate]] = {
    "bug_fix": [
        ValidationGate("patch_applies", description="Patch applies when a patch is proposed."),
        ValidationGate("syntax_valid", description="No obvious syntax or path errors are present."),
        ValidationGate("related_tests", required=False, description="Related tests pass if available."),
    ],
    "refactor": [
        ValidationGate("patch_applies"),
        ValidationGate("no_public_api_break", required=False),
        ValidationGate("tests_pass", required=False),
    ],
    "test_generation": [
        ValidationGate("tests_added"),
        ValidationGate("tests_run", required=False),
        ValidationGate("fail_before_pass_after", required=False),
    ],
    "repo_analysis": [
        ValidationGate("cites_real_files"),
        ValidationGate("no_hallucinated_paths"),
    ],
    "security": [
        ValidationGate("patch_applies"),
        ValidationGate("no_hallucinated_paths"),
        ValidationGate("security_review", required=False),
    ],
    "performance": [
        ValidationGate("patch_applies"),
        ValidationGate("benchmarks_or_tests", required=False),
    ],
    "feature": [
        ValidationGate("patch_applies", description="Patch applies when a patch is proposed."),
        ValidationGate("syntax_valid", description="No obvious syntax or path errors are present."),
        ValidationGate("related_tests", required=False),
    ],
    "ui_change": [
        ValidationGate("patch_applies"),
        ValidationGate("syntax_valid"),
        ValidationGate("visual_or_snapshot_check", required=False),
    ],
    "build_fix": [
        ValidationGate("patch_applies"),
        ValidationGate("syntax_valid"),
        ValidationGate("build_or_tests", required=False),
    ],
    "migration": [
        ValidationGate("patch_applies"),
        ValidationGate("no_public_api_break", required=False),
        ValidationGate("tests_pass", required=False),
    ],
    "docs": [
        ValidationGate("answered_task"),
    ],
    "explanation": [
        ValidationGate("answered_task"),
    ],
}


def validation_gates_for_task(task_type: str) -> list[ValidationGate]:
    return list(QUALITY_GATES.get(str(task_type or "").lower(), [ValidationGate("answered_task")]))


def evaluate_validation_gates(
    *,
    task_type: str,
    checks: dict[str, Any],
    response_text: str,
) -> list[dict[str, Any]]:
    text = str(response_text or "").lower()
    results: list[dict[str, Any]] = []
    for gate in validation_gates_for_task(task_type):
        status = _gate_status(gate.name, checks, text)
        results.append(
            {
                **gate.to_dict(),
                "status": status,
                "passed": status in {"passed", "not_applicable"},
            }
        )
    return results


def required_gate_failed(gates: list[dict[str, Any]]) -> bool:
    return any(bool(gate.get("required")) and gate.get("passed") is False for gate in gates)


def _gate_status(name: str, checks: dict[str, Any], text: str) -> str:
    if name == "answered_task":
        return "passed" if checks.get("answered_task") else "failed"
    if name == "patch_applies":
        value = checks.get("patch_applies")
        return "passed" if value in {"yes", "not_applicable"} else "failed"
    if name == "syntax_valid":
        syntax = checks.get("syntax_valid")
        return "failed" if syntax == "failed" else "passed"
    if name in {"no_public_api_break", "security_review"}:
        return "passed" if checks.get("hallucinated_files") == "none" else "failed"
    if name in {"related_tests", "tests_pass", "tests_run", "benchmarks_or_tests", "build_or_tests", "visual_or_snapshot_check"}:
        tests = checks.get("tests")
        if tests == "failed":
            return "failed"
        if tests == "passed":
            return "passed"
        return "not_applicable"
    if name == "tests_added":
        return "passed" if ("test" in text and ("add" in text or "create" in text or "write" in text or "diff --git" in text)) else "failed"
    if name == "fail_before_pass_after":
        return "passed" if "fail" in text and "pass" in text else "not_applicable"
    if name == "cites_real_files":
        return "passed" if checks.get("hallucinated_files") == "none" else "failed"
    if name == "no_hallucinated_paths":
        return "passed" if checks.get("hallucinated_files") == "none" else "failed"
    return "not_applicable"
