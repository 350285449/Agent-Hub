from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import HubConfig
from . import BenchmarkTask, default_benchmark_tasks


DEFAULT_CORPUS_DIR = "benchmarks"
MAX_BENCHMARK_TASKS = 500


@dataclass(frozen=True, slots=True)
class BenchmarkDataset:
    name: str
    route: str
    tasks: list[BenchmarkTask]
    source: str
    requested_limit: int
    generated: bool = False

    @property
    def fingerprint(self) -> str:
        return benchmark_dataset_fingerprint(self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "route": self.route,
            "task_count": len(self.tasks),
            "requested_limit": self.requested_limit,
            "fingerprint": self.fingerprint,
            "source": self.source,
            "generated": self.generated,
            "public_repository_path": "benchmarks/",
        }


def resolve_benchmark_dataset(
    config: HubConfig,
    *,
    dataset: str = "",
    route: str = "cloud-agent",
    limit: int = 0,
    corpus_dir: str | Path | None = None,
) -> BenchmarkDataset:
    root = resolve_corpus_path(config, corpus_dir)
    name = str(dataset or "").strip()
    requested_limit = _requested_limit(name, limit)
    requested_route = _requested_route(name, route)
    source = root
    generated = False

    if name and Path(name).exists():
        source = Path(name)
        tasks = load_benchmark_corpus(source, route=requested_route, limit=requested_limit)
        dataset_name = Path(name).stem or "custom"
    elif name and (root / name).exists():
        source = root / name
        tasks = load_benchmark_corpus(source, route=requested_route, limit=requested_limit)
        dataset_name = name
    else:
        tasks = _category_tasks(root, name, route=requested_route, limit=requested_limit)
        dataset_name = name or f"{requested_route}-{requested_limit}"
        if len(tasks) < requested_limit:
            base_tasks = tasks or load_benchmark_corpus(root, route=requested_route, limit=MAX_BENCHMARK_TASKS)
            if not base_tasks:
                base_tasks = default_benchmark_tasks(route=requested_route)
            tasks = _expand_tasks(base_tasks, requested_limit, route=requested_route)
            generated = len(base_tasks) < requested_limit

    if not tasks:
        tasks = default_benchmark_tasks(route=requested_route)[:requested_limit]
        generated = True

    tasks = tasks[:requested_limit]
    return BenchmarkDataset(
        name=dataset_name,
        route=requested_route,
        tasks=tasks,
        source=str(source),
        requested_limit=requested_limit,
        generated=generated,
    )


def load_benchmark_corpus(path: str | Path, *, route: str, limit: int = 50) -> list[BenchmarkTask]:
    root = Path(path)
    if not root.exists():
        return []
    cap = _cap(limit)
    tasks: list[BenchmarkTask] = []
    files = [root] if root.is_file() else sorted(root.glob("**/*.jsonl"))
    if root.is_dir() and root.name != "public-150":
        files = [
            path
            for path in files
            if "public-150" not in path.relative_to(root).parts
        ]
    for file_path in files:
        category = file_path.parent.name
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            task = task_from_payload(payload, route=route, fallback_type=category)
            if task is None:
                continue
            tasks.append(task)
            if len(tasks) >= cap:
                return tasks
    return tasks


def task_from_payload(payload: dict[str, Any], *, route: str, fallback_type: str = "general") -> BenchmarkTask | None:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return None
    keywords = payload.get("expected_keywords")
    return BenchmarkTask(
        str(payload.get("type") or payload.get("task") or fallback_type or "general"),
        prompt,
        [
            str(item)
            for item in keywords
            if isinstance(keywords, list) and str(item).strip()
        ]
        if isinstance(keywords, list)
        else [],
        str(payload.get("route") or route),
        bool(payload.get("needs_tools")),
    )


def benchmark_dataset_fingerprint(tasks: list[BenchmarkTask]) -> str:
    canonical = [
        {
            "type": task.type,
            "prompt": task.prompt,
            "expected_keywords": list(task.expected_keywords),
            "route": task.route,
            "needs_tools": task.needs_tools,
        }
        for task in tasks
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def benchmark_tasks_from_report(report: dict[str, Any]) -> list[BenchmarkTask]:
    route = str(report.get("route") or "cloud-agent")
    tasks: list[BenchmarkTask] = []
    for row in report.get("results", []):
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        expected = row.get("expected_keywords")
        tasks.append(
            BenchmarkTask(
                str(row.get("task_type") or "general"),
                prompt,
                [str(item) for item in expected if isinstance(expected, list)] if isinstance(expected, list) else [],
                str(row.get("route") or route),
                bool(row.get("needs_tools")),
            )
        )
    return tasks


def verify_benchmark_report(
    config: HubConfig,
    *,
    report_path: str | Path | None = None,
    dataset: str = "",
    corpus_dir: str | Path | None = None,
) -> dict[str, Any]:
    report, path = load_benchmark_report(config, report_path)
    checks: list[dict[str, Any]] = []
    if not report:
        return {
            "object": "agent_hub.benchmark_verification",
            "ok": False,
            "report_path": str(path) if path else "",
            "checks": [{"name": "report_found", "ok": False, "detail": "No benchmark report was found."}],
        }

    checks.append(
        {
            "name": "schema",
            "ok": report.get("object") == "agent_hub.benchmark_proof",
            "detail": str(report.get("object") or "missing object"),
        }
    )
    report_dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    dataset_name = dataset or str(report_dataset.get("name") or report.get("dataset_name") or "")
    task_count = int(report.get("task_count") or len(report.get("results", [])) or report_dataset.get("task_count") or 50)
    resolved = resolve_benchmark_dataset(
        config,
        dataset=dataset_name,
        route=str(report.get("route") or "cloud-agent"),
        limit=task_count,
        corpus_dir=corpus_dir,
    )
    expected_fingerprint = str(report_dataset.get("fingerprint") or report.get("dataset_fingerprint") or "")
    current_fingerprint = resolved.fingerprint
    checks.append(
        {
            "name": "dataset_fingerprint",
            "ok": bool(expected_fingerprint) and expected_fingerprint == current_fingerprint,
            "detail": f"report={expected_fingerprint or 'missing'} current={current_fingerprint}",
        }
    )
    checks.append(
        {
            "name": "task_count",
            "ok": int(report.get("task_count") or 0) == len(resolved.tasks),
            "detail": f"report={int(report.get('task_count') or 0)} dataset={len(resolved.tasks)}",
        }
    )
    result_tasks = benchmark_tasks_from_report(report)
    result_fingerprint = benchmark_dataset_fingerprint(result_tasks) if result_tasks else ""
    checks.append(
        {
            "name": "results_match_dataset",
            "ok": bool(result_fingerprint) and result_fingerprint == current_fingerprint,
            "detail": f"results={result_fingerprint or 'missing'} current={current_fingerprint}",
        }
    )
    ok = all(bool(check.get("ok")) for check in checks)
    return {
        "object": "agent_hub.benchmark_verification",
        "ok": ok,
        "report_path": str(path) if path else "",
        "dataset": resolved.to_dict(),
        "checks": checks,
        "rerun_command": (
            f"agent-hub benchmark --dataset {resolved.name} --route {resolved.route} "
            f"--export results.json"
        ),
    }


def load_benchmark_report(config: HubConfig, report_path: str | Path | None = None) -> tuple[dict[str, Any], Path | None]:
    candidates: list[Path] = []
    if report_path and str(report_path) != "latest":
        candidates.append(Path(report_path))
    reports_dir = state_path(config, "benchmark_reports")
    if reports_dir.exists():
        candidates.extend(sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True))
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload, path
    return {}, candidates[0] if candidates else None


def resolve_corpus_path(config: HubConfig, corpus_dir: str | Path | None) -> Path:
    if corpus_dir:
        return Path(corpus_dir)
    workspace_corpus = workspace_path(config, DEFAULT_CORPUS_DIR)
    if workspace_corpus.exists():
        return workspace_corpus
    bundled_corpus = Path(__file__).resolve().parents[2] / DEFAULT_CORPUS_DIR
    if bundled_corpus.exists():
        return bundled_corpus
    return workspace_corpus


def state_path(config: HubConfig, name: str) -> Path:
    root = Path(config.state_dir)
    if not root.is_absolute():
        root = workspace_path(config, str(root))
    return root / name


def workspace_path(config: HubConfig, name: str) -> Path:
    root = Path(config.workspace_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root / name


def _category_tasks(root: Path, name: str, *, route: str, limit: int) -> list[BenchmarkTask]:
    category = _category_from_name(name)
    if category == "coding" and limit > 10:
        return load_benchmark_corpus(root, route=route, limit=limit)
    if category and (root / category).exists():
        return load_benchmark_corpus(root / category, route=route, limit=limit)
    return load_benchmark_corpus(root, route=route, limit=limit)


def _category_from_name(name: str) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return ""
    match = re.match(r"(?P<category>[a-z][a-z0-9_-]*?)-\d+$", text)
    return match.group("category") if match else text


def _requested_limit(name: str, limit: int) -> int:
    try:
        explicit = int(limit)
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return _cap(explicit)
    text = str(name or "")
    match = re.search(r"-(\d+)$", text)
    if match:
        return _cap(match.group(1))
    return 50


def _requested_route(name: str, route: str) -> str:
    return route


def _expand_tasks(tasks: list[BenchmarkTask], limit: int, *, route: str) -> list[BenchmarkTask]:
    if not tasks:
        return []
    expanded: list[BenchmarkTask] = []
    for index in range(_cap(limit)):
        task = tasks[index % len(tasks)]
        expanded.append(
            BenchmarkTask(
                task.type,
                task.prompt,
                list(task.expected_keywords),
                task.route or route,
                task.needs_tools,
            )
        )
    return expanded


def _cap(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 50
    return max(1, min(MAX_BENCHMARK_TASKS, number))


__all__ = [
    "BenchmarkDataset",
    "MAX_BENCHMARK_TASKS",
    "benchmark_dataset_fingerprint",
    "benchmark_tasks_from_report",
    "load_benchmark_corpus",
    "load_benchmark_report",
    "resolve_benchmark_dataset",
    "resolve_corpus_path",
    "state_path",
    "verify_benchmark_report",
]
