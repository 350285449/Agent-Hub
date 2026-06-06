from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentConfig, HubConfig, normalize_provider
from .repository import RepositoryIndex, RepositoryIndexer
from .security.command_runner import CommandExecutionRequest, CommandRunnerError, run_workspace_command


REPOSITORY_INTELLIGENCE_FILE = "repository_intelligence.json"
MAX_DEPENDENCIES = 80


@dataclass(slots=True)
class RepositoryDNA:
    """Stable, product-facing profile of a workspace."""

    root: str
    profile_id: str
    fingerprint: str
    project: str
    language: str
    architecture: str
    code_style: str
    testing: str
    frameworks: list[str] = field(default_factory=list)
    design_patterns: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    risk_areas: list[str] = field(default_factory=list)
    package_files: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    commit_history: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    confidence: float = 0.0
    generated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.repository_dna",
            "root": self.root,
            "profile_id": self.profile_id,
            "fingerprint": self.fingerprint,
            "project": self.project,
            "language": self.language,
            "architecture": self.architecture,
            "code_style": self.code_style,
            "testing": self.testing,
            "frameworks": list(self.frameworks),
            "design_patterns": list(self.design_patterns),
            "dependencies": list(self.dependencies),
            "risk_areas": list(self.risk_areas),
            "package_files": list(self.package_files),
            "source_counts": dict(self.source_counts),
            "commit_history": dict(self.commit_history),
            "summary": self.summary,
            "confidence": self.confidence,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepositoryDNA":
        return cls(
            root=str(data.get("root") or ""),
            profile_id=str(data.get("profile_id") or ""),
            fingerprint=str(data.get("fingerprint") or ""),
            project=str(data.get("project") or "Repository"),
            language=str(data.get("language") or "unknown"),
            architecture=str(data.get("architecture") or "Unknown"),
            code_style=str(data.get("code_style") or "Unknown"),
            testing=str(data.get("testing") or "Unknown"),
            frameworks=_string_list(data.get("frameworks")),
            design_patterns=_string_list(data.get("design_patterns")),
            dependencies=_string_list(data.get("dependencies")),
            risk_areas=_string_list(data.get("risk_areas")),
            package_files=_string_list(data.get("package_files")),
            source_counts={
                str(key): int(value)
                for key, value in (data.get("source_counts") or {}).items()
                if isinstance(key, str) and isinstance(value, int)
            },
            commit_history=dict(data.get("commit_history") or {}),
            summary=str(data.get("summary") or ""),
            confidence=_safe_float(data.get("confidence"), 0.0),
            generated_at=_safe_float(data.get("generated_at"), 0.0),
        )


class RepositoryIntelligenceStore:
    """Persist Repository DNA and workspace memory per configured state dir."""

    def __init__(
        self,
        root: str | Path,
        state_dir: str | Path,
        *,
        ignore_patterns: list[str] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / REPOSITORY_INTELLIGENCE_FILE
        self.ignore_patterns = ignore_patterns or []
        self._cached_dna: RepositoryDNA | None = None
        self._cached_memory: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: HubConfig) -> "RepositoryIntelligenceStore":
        return cls(
            config.workspace_dir,
            config.state_dir,
            ignore_patterns=getattr(config, "repo_ignore_patterns", []),
        )

    def repository_dna(self, *, force: bool = False) -> RepositoryDNA:
        if not force and self._cached_dna is not None:
            return self._cached_dna
        cache_key = _cache_key(self.root)
        state = self._load_state()
        cached = state.get("repository_dna") if isinstance(state.get("repository_dna"), dict) else {}
        if not force and cached.get("cache_key") == cache_key:
            try:
                self._cached_dna = RepositoryDNA.from_dict(cached)
                return self._cached_dna
            except Exception:
                pass
        index = RepositoryIndexer(self.root, ignore_patterns=self.ignore_patterns).index(max_files=2500)
        dna = analyze_repository_dna(index, cache_key=cache_key)
        self._cached_dna = dna
        self._save_state(
            {
                **state,
                "version": 1,
                "updated_at": time.time(),
                "repository_dna": {**dna.to_dict(), "cache_key": cache_key},
                "workspace_memory": _workspace_memory_from_dna(
                    dna,
                    existing=state.get("workspace_memory") if isinstance(state.get("workspace_memory"), dict) else {},
                ),
            }
        )
        return dna

    def workspace_memory(self, *, force: bool = False) -> dict[str, Any]:
        if not force and self._cached_memory is not None:
            return dict(self._cached_memory)
        dna = self.repository_dna(force=force)
        state = self._load_state()
        memory = state.get("workspace_memory") if isinstance(state.get("workspace_memory"), dict) else {}
        if not memory:
            memory = _workspace_memory_from_dna(dna, existing={})
            self._save_state({**state, "workspace_memory": memory})
        result = {
            "object": "agent_hub.workspace_memory",
            "repository_profile_id": dna.profile_id,
            "fingerprint": dna.fingerprint,
            "facts": list(memory.get("facts") or []),
            "remembered_files": list(memory.get("remembered_files") or []),
            "last_updated_at": memory.get("last_updated_at", dna.generated_at),
            "cached": True,
        }
        self._cached_memory = dict(result)
        return result

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        _atomic_write_text(self.path, json.dumps(state, indent=2, ensure_ascii=False))


def analyze_repository_dna(index: RepositoryIndex, *, cache_key: str = "") -> RepositoryDNA:
    root = index.root
    languages = _language_counts(index)
    language = _primary_language(languages)
    dependencies, package_frameworks = _dependencies_and_frameworks(root, index.package_files)
    frameworks = _dedupe([*package_frameworks, *_frameworks_from_files(index, language)])
    project = _project_type(root, index, language, frameworks, dependencies)
    architecture = _architecture(index, project, language, frameworks)
    code_style = _code_style(root, index, language)
    design_patterns = _design_patterns(index)
    testing = _testing_strength(index)
    risk_areas = _risk_areas(index, dependencies, frameworks)
    commit_history = _commit_history(root)
    fingerprint = _fingerprint(index, cache_key=cache_key, dependencies=dependencies)
    profile_id = _profile_id(root, project, language)
    summary = _summary(
        project=project,
        language=language,
        architecture=architecture,
        code_style=code_style,
        testing=testing,
        risk_areas=risk_areas,
    )
    confidence = _confidence(index, dependencies, commit_history)
    return RepositoryDNA(
        root=str(root),
        profile_id=profile_id,
        fingerprint=fingerprint,
        project=project,
        language=language,
        architecture=architecture,
        code_style=code_style,
        testing=testing,
        frameworks=frameworks,
        design_patterns=design_patterns,
        dependencies=dependencies[:MAX_DEPENDENCIES],
        risk_areas=risk_areas,
        package_files=list(index.package_files),
        source_counts=languages,
        commit_history=commit_history,
        summary=summary,
        confidence=confidence,
        generated_at=time.time(),
    )


def repository_routing_signal(
    agent: AgentConfig,
    classification: Any,
    dna: RepositoryDNA | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a repository-specific score adjustment for one candidate model."""

    if dna is None:
        return _inactive_repo_signal(agent, "Repository DNA is not available yet.")
    dna_dict = dna.to_dict() if hasattr(dna, "to_dict") else dict(dna)
    family = _model_family(agent)
    project = str(dna_dict.get("project") or "").lower()
    language = str(dna_dict.get("language") or "").lower()
    architecture = str(dna_dict.get("architecture") or "").lower()
    testing = str(dna_dict.get("testing") or "").lower()
    risks = {str(item).lower() for item in dna_dict.get("risk_areas") or []}
    framework_text = " ".join(str(item).lower() for item in dna_dict.get("frameworks") or [])
    task = classification.to_dict() if hasattr(classification, "to_dict") else dict(classification or {})
    task_type = str(task.get("task_type") or "general").lower()
    complexity = str(task.get("complexity") or "low").lower()
    adjustment = 0.0
    rules: list[str] = []

    if "minecraft" in project or (language == "java" and "event" in architecture):
        adjustment += _family_bonus(family, {"claude": 5.0, "deepseek": 2.0, "gemini": 1.0})
        rules.append("minecraft/java event-driven repositories favor strong code reasoning.")
    if language == "rust":
        adjustment += _family_bonus(family, {"deepseek": 4.0, "gpt": 2.0, "claude": 1.5})
        rules.append("rust repositories favor models with strong systems-code performance.")
    if language == "python" and any(word in project for word in ("automation", "cli", "package")):
        adjustment += _family_bonus(family, {"gemini": 3.0, "gpt": 2.0, "deepseek": 1.0})
        rules.append("python automation/CLI repositories favor fast generalist coding models.")
    if any(word in project for word in ("dashboard", "frontend", "web app")) or any(
        marker in framework_text for marker in ("react", "grafana", "vite", "next")
    ):
        adjustment += _family_bonus(family, {"gpt": 4.0, "gemini": 2.0, "claude": 1.0})
        rules.append("frontend/dashboard repositories favor UI and TypeScript-capable models.")
    if "event" in architecture:
        adjustment += _family_bonus(family, {"claude": 1.5, "gemini": 1.0})
        rules.append("event-driven architecture adds a reasoning-model preference.")
    if testing == "weak" and task_type in {"coding", "debug", "test_generation", "tool_use"}:
        adjustment += min(1.5, float(agent.reasoning_score or 0.0) * 1.5)
        rules.append("weak tests increase preference for review-capable models.")
    if complexity == "high" or risks & {"networking", "serialization", "security", "shell commands"}:
        adjustment += min(1.5, float(agent.reasoning_score or 0.0) * 1.2 + float(agent.coding_score or 0.0) * 0.4)
        rules.append("risk areas increase preference for high reasoning/coding scores.")

    adjustment = _clamp(adjustment, -8.0, 8.0)
    active = abs(adjustment) >= 0.25
    return {
        "active": active,
        "agent": agent.name,
        "provider": agent.provider,
        "model": agent.model,
        "model_family": family,
        "adjustment": round(adjustment, 4) if active else 0.0,
        "raw_adjustment": round(adjustment, 4),
        "repository_profile_id": dna_dict.get("profile_id", ""),
        "project": dna_dict.get("project", ""),
        "language": dna_dict.get("language", ""),
        "architecture": dna_dict.get("architecture", ""),
        "rules": rules[:6],
        "summary": (
            f"Repository DNA adjusted {agent.name} by {adjustment:+.2f} for "
            f"{dna_dict.get('project', 'this repository')}."
            if active
            else "Repository DNA had no meaningful effect on this candidate."
        ),
    }


def build_failure_prediction(
    *,
    decision: Any,
    workflow_selection: dict[str, Any] | None = None,
    config: HubConfig | None = None,
) -> dict[str, Any]:
    decision_dict = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    candidates = decision_dict.get("candidate_scores") if isinstance(decision_dict.get("candidate_scores"), list) else []
    selected = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    health = selected.get("health") if isinstance(selected.get("health"), dict) else {}
    adaptive = selected.get("adaptive") if isinstance(selected.get("adaptive"), dict) else {}
    memory = selected.get("routing_memory") if isinstance(selected.get("routing_memory"), dict) else {}
    classification = decision_dict.get("task_classification") if isinstance(decision_dict.get("task_classification"), dict) else {}
    workflow = workflow_selection if isinstance(workflow_selection, dict) else {}
    probability = 0.62
    reliability = _safe_float(health.get("reliability_score"), 0.7)
    probability += (reliability - 0.7) * 0.35
    if health.get("success_count"):
        probability += min(0.08, int(health.get("success_count", 0)) * 0.008)
    if health.get("degraded"):
        probability -= 0.18
    if adaptive.get("active"):
        scorecard = adaptive.get("scorecard") if isinstance(adaptive.get("scorecard"), dict) else {}
        probability += (_safe_float(scorecard.get("smoothed_success_rate"), 0.62) - 0.62) * 0.25
    if memory.get("attempts"):
        probability += (_safe_float(memory.get("success_rate"), 0.62) - 0.62) * 0.28
    risk = str(decision_dict.get("risk") or classification.get("risk_level") or "low").lower()
    complexity = str(decision_dict.get("complexity") or classification.get("complexity") or "low").lower()
    if risk in {"high", "critical"}:
        probability -= 0.12 if risk == "high" else 0.20
    if complexity == "high":
        probability -= 0.08
    pattern = str(workflow.get("pattern") or decision_dict.get("selected_workflow") or "").lower()
    if pattern in {"reviewed_worker", "team_reviewed"} and risk in {"high", "critical"}:
        probability += 0.08
    if pattern == "team_reviewed":
        probability += 0.04
    probability = _clamp(probability, 0.05, 0.98)
    estimated_cost = _safe_optional_float(selected.get("estimated_cost_usd"))
    latency_ms = _safe_float(health.get("average_latency_ms"), 0.0)
    if latency_ms <= 0:
        latency_ms = _default_latency_ms(pattern, complexity)
    role_multiplier = {
        "direct_route": 1.0,
        "single_worker": 1.7,
        "planned_worker": 2.4,
        "reviewed_worker": 3.0,
        "team_reviewed": 4.2,
    }.get(pattern, 1.6)
    estimated_time_seconds = max(1.0, latency_ms / 1000.0 * role_multiplier)
    repair_attempts = int(getattr(config, "validation_repair_attempts", 3) if config is not None else 3)
    return {
        "object": "agent_hub.failure_prediction",
        "chance_of_success": round(probability, 4),
        "chance_of_success_percent": round(probability * 100, 1),
        "estimated_cost_usd": estimated_cost,
        "estimated_time_seconds": round(estimated_time_seconds, 2),
        "basis": [
            "provider health",
            "adaptive samples" if adaptive.get("active") else "adaptive cold start",
            "routing memory" if memory.get("attempts") else "routing memory cold start",
            "task complexity",
            "workflow shape",
        ],
        "repair_loop": {
            "enabled": bool(getattr(config, "auto_validate_after_edits", True) if config is not None else True),
            "max_attempts": repair_attempts,
            "strategy": "generate_verify_repair",
        },
    }


def build_cost_optimizer_summary(
    *,
    decision: Any | None = None,
    routing_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    decision_dict = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    explanation = decision_dict.get("explanation") if isinstance(decision_dict.get("explanation"), dict) else {}
    current = explanation.get("cost_savings") if isinstance(explanation.get("cost_savings"), dict) else {}
    totals = _savings_totals(routing_events or [])
    return {
        "object": "agent_hub.cost_optimizer",
        "selected_request": current,
        "saved_today_usd": round(totals["today"], 6),
        "saved_this_month_usd": round(totals["month"], 6),
        "samples": totals["samples"],
        "message": (
            f"You saved ${totals['today']:.2f} today and ${totals['month']:.2f} this month."
            if totals["samples"]
            else "Savings will appear after routing decisions record comparable candidate costs."
        ),
    }


def build_model_performance_database(
    *,
    optimization: dict[str, Any],
    routing_memory: dict[str, Any],
    dna: RepositoryDNA | dict[str, Any] | None,
) -> dict[str, Any]:
    dna_dict = dna.to_dict() if hasattr(dna, "to_dict") else dict(dna or {})
    rows: list[dict[str, Any]] = []
    for row in (optimization.get("model_win_rates", []) if isinstance(optimization, dict) else []):
        if isinstance(row, dict):
            rows.append({**row, "source": "adaptive_learning"})
    for row in (
        routing_memory.get("most_successful_models_by_task_type", [])
        if isinstance(routing_memory, dict)
        else []
    ):
        if isinstance(row, dict):
            rows.append({**row, "source": "routing_memory"})
    return {
        "object": "agent_hub.model_performance_database",
        "repository_profile_id": dna_dict.get("profile_id", ""),
        "project": dna_dict.get("project", ""),
        "language": dna_dict.get("language", ""),
        "rows": rows[:50],
        "best_by_task": _best_by_task(rows),
        "routing_mode": "historical_success_based_routing" if rows else "cold_start_score_based_routing",
    }


def build_autonomous_night_mode_plan(
    *,
    dna: RepositoryDNA | dict[str, Any] | None,
    config: HubConfig,
) -> dict[str, Any]:
    dna_dict = dna.to_dict() if hasattr(dna, "to_dict") else dict(dna or {})
    testing = str(dna_dict.get("testing") or "Unknown")
    risks = list(dna_dict.get("risk_areas") or [])
    commands = _night_mode_commands(dna_dict)
    tasks = [
        "Run repository validation",
        "Review recent routing and workflow failures",
        "Fix low-risk test or lint failures with repair loop",
        "Update docs for verified changes",
        "Prepare PR summaries for human review",
    ]
    if testing.lower() == "weak":
        tasks.insert(1, "Identify missing smoke tests before code edits")
    if risks:
        tasks.insert(1, "Skip high-risk areas without explicit approval: " + ", ".join(risks[:4]))
    return {
        "object": "agent_hub.autonomous_night_mode_plan",
        "enabled": bool(config.autonomous_night_mode_enabled),
        "mode": "validation_only" if config.autonomous_night_mode_enabled else "plan_only",
        "repository_profile_id": dna_dict.get("profile_id", ""),
        "tasks": tasks,
        "validation_commands": commands,
        "safeguards": [
            "no destructive git commands",
            "human review required before PR creation",
            "respect provider and shell permission policy",
            "stop after repeated validation failure",
            "validation-only execution never edits files",
        ],
    }


def run_autonomous_night_mode_validation(
    *,
    dna: RepositoryDNA | dict[str, Any] | None,
    config: HubConfig,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    plan = build_autonomous_night_mode_plan(dna=dna, config=config)
    commands = list(config.validation_commands or plan["validation_commands"])[:5]
    report: dict[str, Any] = {
        "object": "agent_hub.autonomous_night_mode_run",
        "mode": "validation_only",
        "started_at": time.time(),
        "enabled": bool(config.autonomous_night_mode_enabled),
        "ok": False,
        "status": "blocked",
        "commands": commands,
        "results": [],
        "safeguards": list(plan["safeguards"]),
    }
    if not config.autonomous_night_mode_enabled:
        report["reason"] = "autonomous_night_mode_enabled=false"
        return report
    if not config.allow_shell_tools or config.shell_command_policy != "allow":
        report["reason"] = "Night validation requires allow_shell_tools=true and shell_command_policy=allow."
        return report
    if not commands:
        report["reason"] = "No validation commands were detected or configured."
        return report

    report["status"] = "running"
    per_command_timeout = max(1, min(int(timeout_seconds or 180), 600))
    for command in commands:
        try:
            result = run_workspace_command(
                CommandExecutionRequest(
                    command=command,
                    workspace_dir=config.workspace_dir,
                    timeout_seconds=per_command_timeout,
                    state_dir=config.state_dir,
                    source="autonomous_night_mode_validation",
                )
            ).to_dict()
            result["stdout"] = str(result.get("stdout") or "")[-20_000:]
            result["stderr"] = str(result.get("stderr") or "")[-20_000:]
            report["results"].append(result)
            if int(result.get("returncode", 1)) != 0:
                break
        except (CommandRunnerError, subprocess.TimeoutExpired, OSError) as exc:
            report["results"].append({"command": command, "returncode": None, "error": str(exc)})
            break
    report["finished_at"] = time.time()
    report["ok"] = bool(report["results"]) and all(
        result.get("returncode") == 0 for result in report["results"]
    )
    report["status"] = "passed" if report["ok"] else "failed"
    reports_dir = Path(config.state_dir) / "night_mode_reports"
    report_path = reports_dir / f"night-validation-{int(report['started_at'])}.json"
    report["report_path"] = str(report_path)
    _atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False))
    return report


def _dependencies_and_frameworks(root: Path, package_files: list[str]) -> tuple[list[str], list[str]]:
    dependencies: list[str] = []
    frameworks: list[str] = []
    for rel in package_files:
        path = root / rel
        name = path.name.lower()
        if name == "package.json":
            deps = _package_json_dependencies(path)
            dependencies.extend(deps)
            frameworks.extend(_frameworks_from_dependency_names(deps))
        elif name == "pyproject.toml":
            deps = _pyproject_dependencies(path)
            dependencies.extend(deps)
            frameworks.extend(_frameworks_from_dependency_names(deps))
        elif name in {"requirements.txt", "setup.py"}:
            deps = _plain_dependency_file(path)
            dependencies.extend(deps)
            frameworks.extend(_frameworks_from_dependency_names(deps))
        elif name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            deps = _java_dependencies(path)
            dependencies.extend(deps)
            frameworks.extend(_frameworks_from_dependency_names(deps))
        elif name == "cargo.toml":
            deps = _cargo_dependencies(path)
            dependencies.extend(deps)
            frameworks.append("cargo")
        elif name == "go.mod":
            deps = _go_dependencies(path)
            dependencies.extend(deps)
            frameworks.append("go modules")
    return _dedupe([_normalize_dependency(dep) for dep in dependencies if dep])[:MAX_DEPENDENCIES], _dedupe(frameworks)


def _package_json_dependencies(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    deps: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.extend(str(name) for name in value)
    return deps


def _pyproject_dependencies(path: Path) -> list[str]:
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    deps: list[str] = []
    project = data.get("project") if isinstance(data, dict) else {}
    if isinstance(project, dict):
        deps.extend(_dependency_names(project.get("dependencies")))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for values in optional.values():
                deps.extend(_dependency_names(values))
    tool = data.get("tool") if isinstance(data, dict) else {}
    poetry = tool.get("poetry") if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        for key in ("dependencies", "dev-dependencies"):
            value = poetry.get(key)
            if isinstance(value, dict):
                deps.extend(str(name) for name in value if name.lower() != "python")
    return deps


def _dependency_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names = []
    for item in values:
        if isinstance(item, str):
            names.append(re.split(r"[<>=~!;,\[]", item, maxsplit=1)[0].strip())
    return names


def _plain_dependency_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    deps = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        deps.append(re.split(r"[<>=~!;,\[]", stripped, maxsplit=1)[0].strip())
    return deps


def _java_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    deps = re.findall(r"(?:implementation|api|compileOnly|runtimeOnly)\s*\(?\s*['\"]([^'\"]+)['\"]", text)
    deps.extend(re.findall(r"<artifactId>([^<]+)</artifactId>", text))
    return deps


def _cargo_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    deps: list[str] = []
    in_dependencies = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_dependencies = stripped in {"[dependencies]", "[dev-dependencies]", "[build-dependencies]"}
            continue
        if in_dependencies and "=" in stripped:
            deps.append(stripped.split("=", 1)[0].strip())
    return deps


def _go_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [match.group(1) for match in re.finditer(r"^\s*require\s+([^\s]+)", text, flags=re.MULTILINE)]


def _frameworks_from_dependency_names(dependencies: list[str]) -> list[str]:
    haystack = " ".join(dep.lower() for dep in dependencies)
    frameworks = []
    for marker, name in (
        ("react", "react"),
        ("next", "nextjs"),
        ("vite", "vite"),
        ("vue", "vue"),
        ("svelte", "svelte"),
        ("fastapi", "fastapi"),
        ("django", "django"),
        ("flask", "flask"),
        ("pytest", "pytest"),
        ("fabric", "fabric"),
        ("forge", "forge"),
        ("quilt", "quilt"),
        ("grafana", "grafana"),
        ("vscode", "vscode extension"),
    ):
        if marker in haystack:
            frameworks.append(name)
    return _dedupe(frameworks)


def _frameworks_from_files(index: RepositoryIndex, language: str) -> list[str]:
    files = {file.path.lower() for file in index.files}
    frameworks: list[str] = []
    if "vite.config.ts" in files or "vite.config.js" in files:
        frameworks.append("vite")
    if "next.config.js" in files or "next.config.ts" in files:
        frameworks.append("nextjs")
    if any(path.endswith(".tsx") or path.endswith(".jsx") for path in files):
        frameworks.append("react")
    if "fabric.mod.json" in files:
        frameworks.append("fabric")
    if any(path.endswith("mods.toml") for path in files):
        frameworks.append("forge")
    if language == "python" and any("tests/" in path for path in files):
        frameworks.append("pytest")
    return _dedupe(frameworks)


def _project_type(
    root: Path,
    index: RepositoryIndex,
    language: str,
    frameworks: list[str],
    dependencies: list[str],
) -> str:
    files = {file.path.lower() for file in index.files}
    deps = " ".join(dep.lower() for dep in dependencies)
    framework_text = " ".join(frameworks).lower()
    root_name = root.name.replace("-", " ").replace("_", " ").strip()
    if "fabric.mod.json" in files or any(path.endswith("mods.toml") for path in files) or "minecraft" in deps:
        return "Minecraft Mod"
    if "grafana" in deps or "grafana" in root_name.lower():
        return "Grafana Dashboard"
    if "vscode extension" in framework_text or "vscode-extension/package.json" in files:
        return "VS Code Extension"
    if any(item in framework_text for item in ("react", "nextjs", "vite", "vue", "svelte")):
        return "Frontend Web App"
    if language == "rust":
        return "Rust Engine" if any("engine" in path for path in files) else "Rust Crate"
    if language == "python" and any(path.startswith("scripts/") for path in files):
        return "Python Automation"
    if language == "python" and "pyproject.toml" in files:
        return "Python Package"
    if language == "java":
        return "Java Application"
    if root_name:
        return root_name.title()
    return "Repository"


def _architecture(index: RepositoryIndex, project: str, language: str, frameworks: list[str]) -> str:
    files = [file.path.lower() for file in index.files]
    imports = " ".join(" ".join(file.imports).lower() for file in index.files[:500])
    file_text = " ".join(files)
    if "minecraft" in project.lower() or "event" in file_text or "events.py" in files or "event" in imports:
        return "Event Driven"
    if "routes" in file_text and "services" in file_text:
        return "Layered Service"
    if "router" in file_text and ("provider" in file_text or "adapter" in file_text):
        return "Router / Provider Adapter"
    if any(framework in frameworks for framework in ("react", "vue", "svelte")):
        return "Component Based"
    if language == "python" and ("cli.py" in files or any(path.endswith("/cli.py") for path in files)):
        return "Command Pipeline"
    if any(path.startswith("tests/") for path in files):
        return "Modular"
    return "Unknown"


def _code_style(root: Path, index: RepositoryIndex, language: str) -> str:
    sample = _sample_source_text(root, index, language)
    if not sample:
        return "Unknown"
    class_count = len(re.findall(r"^\s*class\s+\w+", sample, flags=re.MULTILINE))
    function_count = len(re.findall(r"^\s*(?:def|function)\s+\w+|=>", sample, flags=re.MULTILINE))
    dataclass_count = sample.count("@dataclass")
    type_hint_count = len(re.findall(r"\w+\s*:\s*[\w\[\]|.]+", sample))
    if dataclass_count >= 2 or type_hint_count >= 20:
        return "Typed Imperative"
    if class_count > function_count * 0.6:
        return "Object Oriented"
    if function_count >= 8:
        return "Imperative"
    return "Mixed"


def _design_patterns(index: RepositoryIndex) -> list[str]:
    files = " ".join(file.path.lower() for file in index.files)
    patterns: list[str] = []
    for marker, name in (
        ("router", "Router"),
        ("provider", "Provider Adapter"),
        ("workflow", "Workflow"),
        ("middleware", "Middleware"),
        ("registry", "Registry"),
        ("plugin", "Plugin"),
        ("events", "Event Bus"),
        ("factory", "Factory"),
        ("store", "Persistent Store"),
        ("service", "Application Service"),
    ):
        if marker in files:
            patterns.append(name)
    return _dedupe(patterns)[:10]


def _testing_strength(index: RepositoryIndex) -> str:
    source = sum(1 for file in index.files if file.language not in {"markdown", "json", "text", "yaml", "toml"})
    tests = sum(1 for file in index.files if file.path.startswith("tests/") or "test" in Path(file.path).name.lower())
    if tests <= 0:
        return "Weak"
    ratio = tests / max(1, source)
    if tests >= 20 or ratio >= 0.25:
        return "Strong"
    if tests >= 5 or ratio >= 0.10:
        return "Moderate"
    return "Weak"


def _risk_areas(index: RepositoryIndex, dependencies: list[str], frameworks: list[str]) -> list[str]:
    files = " ".join(file.path.lower() for file in index.files)
    deps = " ".join(dep.lower() for dep in dependencies)
    risks: list[str] = []
    for marker, risk in (
        ("socket", "Networking"),
        ("http", "Networking"),
        ("api", "Networking"),
        ("json", "Serialization"),
        ("yaml", "Serialization"),
        ("toml", "Serialization"),
        ("auth", "Authentication"),
        ("secret", "Secrets"),
        ("permission", "Permissions"),
        ("shell", "Shell Commands"),
        ("subprocess", "Shell Commands"),
        ("plugin", "Plugins"),
        ("state", "State Persistence"),
        ("database", "Database"),
        ("stripe", "Payments"),
    ):
        if marker in files or marker in deps:
            risks.append(risk)
    if any(framework in {"fabric", "forge", "quilt"} for framework in frameworks):
        risks.extend(["Networking", "Serialization"])
    return _dedupe(risks)[:10]


def _language_counts(index: RepositoryIndex) -> dict[str, int]:
    return {
        language: count
        for language, count in sorted(index.languages.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    }


def _primary_language(languages: dict[str, int]) -> str:
    for language, _count in languages.items():
        if language not in {"text", "markdown", "json", "yaml", "toml"}:
            return language
    return next(iter(languages), "unknown")


def _commit_history(root: Path) -> dict[str, Any]:
    count = _git_output(root, ["rev-list", "--count", "HEAD"], timeout=2)
    latest = _git_output(root, ["log", "-1", "--format=%h %s"], timeout=2)
    churn = _git_output(root, ["log", "--name-only", "--pretty=format:", "-n", "25"], timeout=2)
    changed = [line.strip().replace("\\", "/") for line in churn.splitlines() if line.strip()]
    hot_files = _top_counts(changed, limit=8)
    return {
        "commit_count": _safe_int(count.strip(), 0),
        "latest": latest.strip(),
        "hot_files": hot_files,
    }


def _git_output(root: Path, args: list[str], *, timeout: float) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _fingerprint(index: RepositoryIndex, *, cache_key: str, dependencies: list[str]) -> str:
    pieces = [
        str(index.root),
        cache_key,
        json.dumps(index.languages, sort_keys=True),
        "|".join(index.package_files),
        "|".join(dependencies[:MAX_DEPENDENCIES]),
    ]
    return hashlib.sha256("\n".join(pieces).encode("utf-8", errors="replace")).hexdigest()[:20]


def _cache_key(root: Path) -> str:
    pieces: list[str] = [str(root)]
    for name in (
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "setup.py",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "fabric.mod.json",
    ):
        path = root / name
        if path.exists():
            stat = path.stat()
            pieces.append(f"{name}:{stat.st_size}:{int(stat.st_mtime)}")
    git_head = _git_output(root, ["rev-parse", "HEAD"], timeout=1).strip()
    if git_head:
        pieces.append(git_head)
    return hashlib.sha256("\n".join(pieces).encode("utf-8", errors="replace")).hexdigest()


def _profile_id(root: Path, project: str, language: str) -> str:
    value = f"{root.as_posix().lower()}|{project.lower()}|{language.lower()}"
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _summary(
    *,
    project: str,
    language: str,
    architecture: str,
    code_style: str,
    testing: str,
    risk_areas: list[str],
) -> str:
    risks = ", ".join(risk_areas[:4]) if risk_areas else "none detected"
    return (
        f"Project: {project}; Language: {language}; Architecture: {architecture}; "
        f"Code style: {code_style}; Testing: {testing}; Risk areas: {risks}."
    )


def _confidence(index: RepositoryIndex, dependencies: list[str], commit_history: dict[str, Any]) -> float:
    score = 0.35
    if index.files:
        score += 0.20
    if index.package_files:
        score += 0.20
    if dependencies:
        score += 0.15
    if commit_history.get("commit_count"):
        score += 0.10
    return round(_clamp(score, 0.0, 0.98), 3)


def _workspace_memory_from_dna(dna: RepositoryDNA, *, existing: dict[str, Any]) -> dict[str, Any]:
    facts = list(existing.get("facts") or [])
    new_facts = [
        f"Repository profile: {dna.project}",
        f"Primary language: {dna.language}",
        f"Architecture: {dna.architecture}",
        f"Code style: {dna.code_style}",
        f"Testing strength: {dna.testing}",
    ]
    if dna.frameworks:
        new_facts.append("Frameworks: " + ", ".join(dna.frameworks[:8]))
    if dna.risk_areas:
        new_facts.append("Risk areas: " + ", ".join(dna.risk_areas[:8]))
    facts = _dedupe([*facts, *new_facts])[-80:]
    remembered_files = _dedupe([
        *[str(item) for item in existing.get("remembered_files") or []],
        *dna.package_files[:20],
    ])[-80:]
    return {
        "facts": facts,
        "remembered_files": remembered_files,
        "last_updated_at": time.time(),
    }


def _sample_source_text(root: Path, index: RepositoryIndex, language: str) -> str:
    chunks: list[str] = []
    for file in index.files:
        if file.language != language:
            continue
        path = root / file.path
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[:4000])
        except OSError:
            continue
        if sum(len(chunk) for chunk in chunks) > 40_000:
            break
    return "\n".join(chunks)


def _night_mode_commands(dna: dict[str, Any]) -> list[str]:
    language = str(dna.get("language") or "").lower()
    package_files = {str(path).lower() for path in dna.get("package_files") or []}
    if language == "python":
        return ["python -m pytest"]
    if "package.json" in package_files or language in {"javascript", "typescript"}:
        return ["npm test", "npm run lint"]
    if language == "rust":
        return ["cargo test"]
    if language == "go":
        return ["go test ./..."]
    if language == "java":
        return ["./gradlew test", "mvn test"]
    return []


def _model_family(agent: AgentConfig) -> str:
    haystack = " ".join(
        str(value).lower()
        for value in (agent.name, agent.provider, agent.provider_type, agent.model)
        if value
    )
    if "claude" in haystack or "anthropic" in haystack:
        return "claude"
    if "deepseek" in haystack:
        return "deepseek"
    if "gemini" in haystack or "google" in haystack:
        return "gemini"
    if "gpt" in haystack or "openai" in haystack or "chatgpt" in haystack or "codex" in haystack:
        return "gpt"
    if "qwen" in haystack:
        return "qwen"
    if "llama" in haystack:
        return "llama"
    return normalize_provider(agent.provider)


def _family_bonus(family: str, weights: dict[str, float]) -> float:
    return float(weights.get(family, 0.0))


def _inactive_repo_signal(agent: AgentConfig, summary: str) -> dict[str, Any]:
    return {
        "active": False,
        "agent": agent.name,
        "provider": agent.provider,
        "model": agent.model,
        "adjustment": 0.0,
        "summary": summary,
    }


def _best_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        task = str(row.get("task_type") or "general")
        attempts = _safe_int(row.get("attempts"), 0)
        success = _safe_float(row.get("success_rate"), 0.0)
        current = best.get(task)
        if current is None or (success, attempts) > (
            _safe_float(current.get("success_rate"), 0.0),
            _safe_int(current.get("attempts"), 0),
        ):
            best[task] = row
    return best


def _savings_totals(events: list[dict[str, Any]]) -> dict[str, Any]:
    now = time.localtime()
    today = 0.0
    month = 0.0
    samples = 0
    for event in events:
        timestamp = _safe_float(event.get("time"), 0.0)
        if timestamp <= 0:
            continue
        decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
        explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
        cost = explanation.get("cost_savings") if isinstance(explanation.get("cost_savings"), dict) else {}
        value = _safe_optional_float(cost.get("estimated_savings_usd"))
        if value is None or value <= 0:
            continue
        local = time.localtime(timestamp)
        if local.tm_year == now.tm_year and local.tm_mon == now.tm_mon:
            month += value
            if local.tm_yday == now.tm_yday:
                today += value
        samples += 1
    return {"today": today, "month": month, "samples": samples}


def _default_latency_ms(pattern: str, complexity: str) -> float:
    if pattern == "team_reviewed":
        return 18_000.0
    if pattern == "reviewed_worker":
        return 12_000.0
    if complexity == "high":
        return 10_000.0
    return 5_000.0


def _top_counts(values: list[str], *, limit: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [
        {"path": path, "count": count}
        for path, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _normalize_dependency(value: str) -> str:
    value = value.strip()
    if ":" in value and "/" not in value:
        return value.split(":")[-1].strip()
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "REPOSITORY_INTELLIGENCE_FILE",
    "RepositoryDNA",
    "RepositoryIntelligenceStore",
    "analyze_repository_dna",
    "repository_routing_signal",
    "build_failure_prediction",
    "build_cost_optimizer_summary",
    "build_model_performance_database",
    "build_autonomous_night_mode_plan",
    "run_autonomous_night_mode_validation",
]
