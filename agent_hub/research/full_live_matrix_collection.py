from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark_generator import generate_research_benchmark
from .data_quality_audit import load_audited_rows, run_data_quality_audit
from .live_matrix_runner import (
    ALLOWED_MODELS,
    CONTEXT_BUDGETS,
    collect_live_matrix,
    live_matrix_path,
)
from .task_generator import REPOSITORIES, TASK_CATEGORIES, benchmark_tasks_path, load_benchmark_tasks
from .telemetry import research_dir


CHECKPOINTS = (50, 100, 250, 500)
MIN_USABLE_ROWS = 500


def run_full_live_matrix_collection(
    state_dir: str | Path,
    *,
    target_usable_rows: int = MIN_USABLE_ROWS,
    repetitions: int = 3,
    chunk_attempts: int = 75,
    timeout_seconds: float | None = None,
    include_disabled_codex: bool = True,
) -> dict[str, str]:
    state = Path(state_dir)
    directory = research_dir(state)
    directory.mkdir(parents=True, exist_ok=True)
    tasks_file = benchmark_tasks_path(state)
    if not tasks_file.exists():
        generate_research_benchmark(state, tasks_per_category=10)

    next_audit_at = _next_multiple(_usable_count(state), 50)
    previous_total = _total_rows(state)
    while True:
        usable, excluded = load_audited_rows(live_matrix_path(state))
        if len(usable) >= target_usable_rows:
            break
        if _all_benchmark_attempts_exhausted(state, repetitions):
            break

        collect_live_matrix(
            state,
            repetitions=repetitions,
            max_runs=max(1, int(chunk_attempts)),
            timeout_seconds=timeout_seconds,
            include_disabled_codex=include_disabled_codex,
        )

        current_total = _total_rows(state)
        usable, excluded = load_audited_rows(live_matrix_path(state))
        if len(usable) >= next_audit_at:
            _write_audit_and_reports(state, usable, excluded)
            while len(usable) >= next_audit_at:
                next_audit_at += 50
        for checkpoint in CHECKPOINTS:
            if len(usable) >= checkpoint:
                _write_checkpoint(state, checkpoint, usable, excluded)
        if current_total == previous_total:
            break
        previous_total = current_total

    usable, excluded = load_audited_rows(live_matrix_path(state))
    _write_audit_and_reports(state, usable, excluded)
    for checkpoint in CHECKPOINTS:
        if len(usable) >= checkpoint:
            _write_checkpoint(state, checkpoint, usable, excluded)
    summary = _write_final_summary(state, usable, excluded)
    return {
        "live_matrix": str(live_matrix_path(state)),
        "balanced_progress_report": str(directory / "balanced_progress_report.md"),
        "collection_summary": str(summary),
    }


def _write_audit_and_reports(state_dir: Path, usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> None:
    run_data_quality_audit(state_dir)
    (research_dir(state_dir) / "balanced_progress_report.md").write_text(
        _progress_markdown(usable, excluded),
        encoding="utf-8",
    )


def _write_checkpoint(state_dir: Path, checkpoint: int, usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> None:
    path = research_dir(state_dir) / f"checkpoint_{checkpoint}.md"
    path.write_text(_checkpoint_markdown(checkpoint, usable, excluded), encoding="utf-8")


def _write_final_summary(state_dir: Path, usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> Path:
    path = research_dir(state_dir) / "live_matrix_collection_summary.md"
    path.write_text(_summary_markdown(usable, excluded), encoding="utf-8")
    return path


def _progress_payload(usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usable_rows": len(usable),
        "excluded_rows": len(excluded),
        "exclusions_by_reason": dict(Counter(row.get("excluded_reason", "unknown") for row in excluded)),
        "rows_per_model": dict(Counter(row["model"] for row in usable)),
        "rows_per_repository": dict(Counter(row["repository"] for row in usable)),
        "rows_per_task_category": dict(Counter(row["category"] for row in usable)),
        "rows_per_context_budget": {str(key): value for key, value in Counter(row["context_budget"] for row in usable).items()},
    }


def _progress_markdown(usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    payload = _progress_payload(usable, excluded)
    lines = [
        "# Balanced Progress Report",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Usable rows: {payload['usable_rows']}",
        f"- Excluded rows: {payload['excluded_rows']}",
        "",
        "## Exclusions By Reason",
        *_dict_lines(payload["exclusions_by_reason"]),
        "",
        "## Rows Per Model",
        *_dict_lines(payload["rows_per_model"]),
        "",
        "## Rows Per Repository",
        *_dict_lines(payload["rows_per_repository"]),
        "",
        "## Rows Per Task Category",
        *_dict_lines(payload["rows_per_task_category"]),
        "",
        "## Rows Per Context Budget",
        *_dict_lines(payload["rows_per_context_budget"]),
        "",
    ]
    return "\n".join(lines)


def _checkpoint_markdown(checkpoint: int, usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    under = _underrepresented(usable)
    balanced = not any(under.values())
    return "\n".join(
        [
            f"# Checkpoint {checkpoint}",
            "",
            f"1. Is the matrix balanced? {'Yes' if balanced else 'No'}",
            f"2. Which models are underrepresented? {_format_list(under['models'])}",
            f"3. Which repositories are underrepresented? {_format_list(under['repositories'])}",
            f"4. Which task categories are underrepresented? {_format_list(under['categories'])}",
            f"5. Current usable row count: {len(usable)}",
            f"6. Current exclusion count: {len(excluded)}",
            "",
        ]
    )


def _summary_markdown(usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    payload = _progress_payload(usable, excluded)
    verdict = _verdict(len(usable), _underrepresented(usable))
    lines = [
        "# Live Matrix Collection Summary",
        "",
        f"- Usable rows collected: {payload['usable_rows']}",
        f"- Exclusions: {payload['excluded_rows']}",
        f"- Model coverage: {payload['rows_per_model']}",
        f"- Repository coverage: {payload['rows_per_repository']}",
        f"- Task coverage: {payload['rows_per_task_category']}",
        f"- Context coverage: {payload['rows_per_context_budget']}",
        f"- Readiness for theory testing: {verdict['readiness']}",
        "",
        f"Final verdict: {verdict['label']}",
        "",
        "No theory evaluation, theory ranking, or new theory generation was performed.",
        "",
    ]
    return "\n".join(lines)


def _underrepresented(usable: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "models": _below_average(Counter(row["model"] for row in usable), ALLOWED_MODELS),
        "repositories": _below_average(Counter(row["repository"] for row in usable), REPOSITORIES),
        "categories": _below_average(Counter(row["category"] for row in usable), TASK_CATEGORIES),
        "context_budgets": _below_average(Counter(row["context_budget"] for row in usable), CONTEXT_BUDGETS),
    }


def _below_average(counter: Counter[Any], expected: Any) -> list[str]:
    keys = list(expected)
    if not keys:
        return []
    average = sum(counter.get(key, 0) for key in keys) / len(keys)
    return [str(key) for key in keys if counter.get(key, 0) < average * 0.9]


def _verdict(usable_rows: int, under: dict[str, list[str]]) -> dict[str, str]:
    if usable_rows < MIN_USABLE_ROWS:
        return {"label": "A) Dataset insufficient", "readiness": "Not ready; fewer than 500 usable rows."}
    if usable_rows >= 1000 and not any(under.values()):
        return {"label": "C) Dataset strong enough for theory evaluation", "readiness": "Ready with strong usable volume and balanced coverage."}
    return {"label": "B) Dataset minimally sufficient", "readiness": "Ready for cautious theory testing; balance gaps should be considered."}


def _dict_lines(payload: dict[Any, Any]) -> list[str]:
    return [f"- {key}: {value}" for key, value in sorted(payload.items(), key=lambda item: str(item[0]))] or ["- none: 0"]


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _usable_count(state_dir: Path) -> int:
    usable, _excluded = load_audited_rows(live_matrix_path(state_dir))
    return len(usable)


def _total_rows(state_dir: Path) -> int:
    path = live_matrix_path(state_dir)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _next_multiple(value: int, size: int) -> int:
    return max(size, ((value // size) + 1) * size)


def _all_benchmark_attempts_exhausted(state_dir: Path, repetitions: int) -> bool:
    tasks = load_benchmark_tasks(benchmark_tasks_path(state_dir))
    expected = len(tasks) * len(CONTEXT_BUDGETS) * max(3, int(repetitions)) * len(ALLOWED_MODELS)
    return bool(expected) and _total_rows(state_dir) >= expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the full live research matrix collection campaign.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--target-usable-rows", type=int, default=MIN_USABLE_ROWS)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--chunk-attempts", type=int, default=75)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--no-include-disabled-codex", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_full_live_matrix_collection(
        args.state_dir,
        target_usable_rows=args.target_usable_rows,
        repetitions=args.repetitions,
        chunk_attempts=args.chunk_attempts,
        timeout_seconds=args.timeout_seconds or None,
        include_disabled_codex=not args.no_include_disabled_codex,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_full_live_matrix_collection"]
