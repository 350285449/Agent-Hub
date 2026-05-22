from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import HubRequest


MAX_LIST_ITEMS = 80
MAX_HISTORY_ITEMS = 30
MAX_DICT_KEYS = 60


@dataclass(slots=True)
class ExecutionNode:
    id: str
    objective: str
    status: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    validation_targets: list[str] = field(default_factory=list)
    estimated_risk: str = "low"
    repair_strategy: str | None = None
    retry_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "ExecutionNode | None":
        if not isinstance(value, dict):
            return None
        node_id = str(value.get("id") or "").strip()
        objective = str(value.get("objective") or "").strip()
        if not node_id or not objective:
            return None
        return cls(
            id=node_id[:120],
            objective=objective[:500],
            status=_execution_status(value.get("status")),
            dependencies=_string_list(value.get("dependencies")),
            affected_files=_string_list(value.get("affected_files")),
            validation_targets=_string_list(value.get("validation_targets")),
            estimated_risk=_risk_value(value.get("estimated_risk")),
            repair_strategy=str(value.get("repair_strategy"))[:500]
            if value.get("repair_strategy")
            else None,
            retry_count=_nonnegative_int(value.get("retry_count")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "objective": self.objective,
            "status": self.status,
            "dependencies": self.dependencies,
            "affected_files": self.affected_files,
            "validation_targets": self.validation_targets,
            "estimated_risk": self.estimated_risk,
            "repair_strategy": self.repair_strategy,
            "retry_count": self.retry_count,
        }

    def compact(self) -> "ExecutionNode":
        self.id = self.id[:120]
        self.objective = self.objective[:500]
        self.status = _execution_status(self.status)
        self.dependencies = _cap(_dedupe(self.dependencies), 20)
        self.affected_files = _cap(_dedupe(_clean_paths(self.affected_files)), MAX_LIST_ITEMS)
        self.validation_targets = _cap(_dedupe(_clean_paths(self.validation_targets)), MAX_LIST_ITEMS)
        self.estimated_risk = _risk_value(self.estimated_risk)
        if self.repair_strategy:
            self.repair_strategy = self.repair_strategy[:500]
        self.retry_count = _nonnegative_int(self.retry_count)
        return self


@dataclass(slots=True)
class ExecutionPlan:
    nodes: list[ExecutionNode] = field(default_factory=list)
    active_node: str | None = None
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    blocked_nodes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "ExecutionPlan":
        if not isinstance(value, dict):
            return cls()
        nodes = [
            node
            for item in value.get("nodes", [])
            if (node := ExecutionNode.from_dict(item)) is not None
        ]
        return cls(
            nodes=nodes,
            active_node=str(value.get("active_node"))[:120]
            if value.get("active_node")
            else None,
            completed_nodes=_string_list(value.get("completed_nodes")),
            failed_nodes=_string_list(value.get("failed_nodes")),
            blocked_nodes=_string_list(value.get("blocked_nodes")),
        ).compact()

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "active_node": self.active_node,
            "completed_nodes": self.completed_nodes,
            "failed_nodes": self.failed_nodes,
            "blocked_nodes": self.blocked_nodes,
        }

    def compact(self) -> "ExecutionPlan":
        self.nodes = [node.compact() for node in self.nodes[:20]]
        existing = {node.id for node in self.nodes}
        self.completed_nodes = _cap(_dedupe([node for node in self.completed_nodes if node in existing]), 40)
        self.failed_nodes = _cap(_dedupe([node for node in self.failed_nodes if node in existing]), 40)
        self.blocked_nodes = _cap(_dedupe([node for node in self.blocked_nodes if node in existing]), 40)
        if self.active_node not in existing:
            self.active_node = None
        return self

    def ensure_default_nodes(self, objectives: list[str]) -> None:
        if self.nodes:
            return
        focus = objectives[0] if objectives else "Complete the requested workspace task"
        base = _slug(focus) or "task"
        inspect_id = f"{base}-inspect"
        edit_id = f"{base}-edit"
        validate_id = f"{base}-validate"
        self.nodes = [
            ExecutionNode(
                id=inspect_id,
                objective=f"Inspect repository context for: {focus}",
                estimated_risk="low",
            ),
            ExecutionNode(
                id=edit_id,
                objective="Apply the minimal grouped patch for the requested change",
                dependencies=[inspect_id],
                estimated_risk="medium",
            ),
            ExecutionNode(
                id=validate_id,
                objective="Validate changed files and affected behavior",
                dependencies=[edit_id],
                estimated_risk="low",
            ),
        ]
        self.activate_next()

    def merge_from(self, other: "ExecutionPlan") -> None:
        by_id = {node.id: node for node in self.nodes}
        for node in other.nodes:
            current = by_id.get(node.id)
            if current is None:
                self.nodes.append(node)
                by_id[node.id] = node
                continue
            current.status = _higher_progress_status(current.status, node.status)
            current.dependencies = _dedupe([*current.dependencies, *node.dependencies])
            current.affected_files = _dedupe([*current.affected_files, *node.affected_files])
            current.validation_targets = _dedupe([*current.validation_targets, *node.validation_targets])
            current.estimated_risk = _higher_risk(current.estimated_risk, node.estimated_risk)
            current.retry_count = max(current.retry_count, node.retry_count)
            if node.repair_strategy:
                current.repair_strategy = node.repair_strategy
        self.completed_nodes = _dedupe([*self.completed_nodes, *other.completed_nodes])
        self.failed_nodes = _dedupe([*self.failed_nodes, *other.failed_nodes])
        self.blocked_nodes = _dedupe([*self.blocked_nodes, *other.blocked_nodes])
        self.active_node = other.active_node or self.active_node
        self.compact()

    def node(self, node_id: str | None) -> ExecutionNode | None:
        if not node_id:
            return None
        return next((node for node in self.nodes if node.id == node_id), None)

    def active(self) -> ExecutionNode | None:
        return self.node(self.active_node)

    def activate_kind(self, kind: str) -> ExecutionNode | None:
        candidates = [node for node in self.nodes if node.id.endswith(f"-{kind}")]
        node = candidates[0] if candidates else None
        if node is None:
            return self.activate_next()
        if node.status in {"pending", "blocked"}:
            node.status = "active"
        self.active_node = node.id
        self.blocked_nodes = [item for item in self.blocked_nodes if item != node.id]
        return node

    def activate_next(self) -> ExecutionNode | None:
        for node in self.nodes:
            if node.status not in {"pending", "blocked"}:
                continue
            if all(dep in self.completed_nodes for dep in node.dependencies):
                node.status = "active"
                self.active_node = node.id
                self.blocked_nodes = [item for item in self.blocked_nodes if item != node.id]
                return node
        self.active_node = None
        return None

    def mark_active_completed(self) -> None:
        node = self.active()
        if node is None:
            return
        node.status = "completed"
        self.completed_nodes = _dedupe([*self.completed_nodes, node.id])
        self.failed_nodes = [item for item in self.failed_nodes if item != node.id]
        self.blocked_nodes = [item for item in self.blocked_nodes if item != node.id]
        self.active_node = None
        self.activate_next()

    def mark_active_failed(self, *, repair_strategy: str | None = None) -> None:
        node = self.active()
        if node is None:
            return
        node.status = "failed"
        node.retry_count += 1
        if repair_strategy:
            node.repair_strategy = repair_strategy[:500]
        self.failed_nodes = _dedupe([*self.failed_nodes, node.id])
        self.active_node = node.id

    def mark_active_blocked(self, *, reason: str | None = None) -> None:
        node = self.active()
        if node is None:
            return
        node.status = "blocked"
        if reason:
            node.repair_strategy = reason[:500]
        self.blocked_nodes = _dedupe([*self.blocked_nodes, node.id])
        self.active_node = node.id

    def add_repair_node(self, objective: str, *, dependencies: list[str], strategy: str) -> ExecutionNode:
        base = _slug(objective) or "repair"
        index = 1
        node_id = f"{base}-repair"
        existing = {node.id for node in self.nodes}
        while node_id in existing:
            index += 1
            node_id = f"{base}-repair-{index}"
        node = ExecutionNode(
            id=node_id,
            objective=objective[:500],
            status="active",
            dependencies=_dedupe(dependencies),
            estimated_risk="medium",
            repair_strategy=strategy[:500],
        )
        self.nodes.append(node)
        self.active_node = node.id
        return node

    def record_files_for_active(self, files: list[str]) -> None:
        node = self.active()
        if node is None:
            return
        node.affected_files = _cap(
            _dedupe([*node.affected_files, *_clean_paths(files)]),
            MAX_LIST_ITEMS,
        )

    def record_validation_targets_for_active(self, targets: list[str]) -> None:
        node = self.active()
        if node is None:
            return
        node.validation_targets = _cap(
            _dedupe([*node.validation_targets, *_clean_paths(targets)]),
            MAX_LIST_ITEMS,
        )


@dataclass(slots=True)
class WorkspaceReasoningState:
    task_id: str
    objectives: list[str] = field(default_factory=list)
    inspected_files: list[str] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)
    related_files: dict[str, list[str]] = field(default_factory=dict)
    planned_edits: list[dict[str, Any]] = field(default_factory=list)
    planned_validations: list[str] = field(default_factory=list)
    validation_history: list[dict[str, Any]] = field(default_factory=list)
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    repository_summary: dict[str, Any] = field(default_factory=dict)
    dependency_map: dict[str, list[str]] = field(default_factory=dict)
    execution_plan: ExecutionPlan = field(default_factory=ExecutionPlan)

    @classmethod
    def for_request(
        cls,
        request: HubRequest,
        *,
        session_data: dict[str, Any] | None = None,
    ) -> "WorkspaceReasoningState":
        raw_state = _reasoning_state_from_raw(request.raw)
        if raw_state is None and isinstance(session_data, dict):
            raw_state = session_data.get("reasoning_state")
        state = cls.from_dict(raw_state, task_id=request.session_id)
        state.add_objectives(_objectives_from_request(request))
        state.ensure_execution_plan()
        return state

    @classmethod
    def from_dict(cls, value: Any, *, task_id: str = "") -> "WorkspaceReasoningState":
        if not isinstance(value, dict):
            return cls(task_id=task_id or "default")
        return cls(
            task_id=str(value.get("task_id") or task_id or "default"),
            objectives=_string_list(value.get("objectives")),
            inspected_files=_string_list(value.get("inspected_files")),
            active_files=_string_list(value.get("active_files")),
            related_files=_dict_of_string_lists(value.get("related_files")),
            planned_edits=_dict_list(value.get("planned_edits")),
            planned_validations=_string_list(value.get("planned_validations")),
            validation_history=_dict_list(value.get("validation_history")),
            repair_history=_dict_list(value.get("repair_history")),
            approval_history=_dict_list(value.get("approval_history")),
            repository_summary=dict(value.get("repository_summary", {}))
            if isinstance(value.get("repository_summary"), dict)
            else {},
            dependency_map=_dict_of_string_lists(value.get("dependency_map")),
            execution_plan=ExecutionPlan.from_dict(value.get("execution_plan")),
        ).compact()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objectives": self.objectives,
            "inspected_files": self.inspected_files,
            "active_files": self.active_files,
            "related_files": self.related_files,
            "planned_edits": self.planned_edits,
            "planned_validations": self.planned_validations,
            "validation_history": self.validation_history,
            "repair_history": self.repair_history,
            "approval_history": self.approval_history,
            "repository_summary": self.repository_summary,
            "dependency_map": self.dependency_map,
            "execution_plan": self.execution_plan.to_dict(),
        }

    def compact(self) -> "WorkspaceReasoningState":
        self.objectives = _cap(_dedupe(self.objectives), MAX_LIST_ITEMS)
        self.inspected_files = _cap(_dedupe(self.inspected_files), MAX_LIST_ITEMS)
        self.active_files = _cap(_dedupe(self.active_files), MAX_LIST_ITEMS)
        self.planned_validations = _cap(_dedupe(self.planned_validations), MAX_LIST_ITEMS)
        self.planned_edits = _cap(self.planned_edits, MAX_HISTORY_ITEMS)
        self.validation_history = _cap(self.validation_history, MAX_HISTORY_ITEMS)
        self.repair_history = _cap(self.repair_history, MAX_HISTORY_ITEMS)
        self.approval_history = _cap(self.approval_history, MAX_HISTORY_ITEMS)
        self.related_files = _compact_dict_lists(self.related_files)
        self.dependency_map = _compact_dict_lists(self.dependency_map)
        self.repository_summary = _compact_dict(self.repository_summary)
        self.execution_plan.compact()
        return self

    def merge_from(self, other: "WorkspaceReasoningState") -> None:
        self.add_objectives(other.objectives)
        self.add_active_files(other.active_files)
        self.add_inspected_files(other.inspected_files)
        for key, files in other.related_files.items():
            self.add_related_files(key, files)
        for key, deps in other.dependency_map.items():
            self.dependency_map[key] = _cap(_dedupe([*self.dependency_map.get(key, []), *deps]), MAX_LIST_ITEMS)
        self.planned_edits = _cap([*self.planned_edits, *other.planned_edits], MAX_HISTORY_ITEMS)
        self.planned_validations = _cap(
            _dedupe([*self.planned_validations, *other.planned_validations]),
            MAX_LIST_ITEMS,
        )
        self.validation_history = _cap(
            [*self.validation_history, *other.validation_history],
            MAX_HISTORY_ITEMS,
        )
        self.repair_history = _cap([*self.repair_history, *other.repair_history], MAX_HISTORY_ITEMS)
        self.approval_history = _cap(
            [*self.approval_history, *other.approval_history],
            MAX_HISTORY_ITEMS,
        )
        self.repository_summary = _compact_dict({**self.repository_summary, **other.repository_summary})
        self.execution_plan.merge_from(other.execution_plan)
        self.compact()

    def add_objectives(self, objectives: list[str]) -> None:
        self.objectives = _cap(_dedupe([*self.objectives, *objectives]), MAX_LIST_ITEMS)
        self.ensure_execution_plan()

    def ensure_execution_plan(self) -> None:
        self.execution_plan.ensure_default_nodes(self.objectives)

    def add_active_files(self, files: list[str]) -> None:
        self.active_files = _cap(_dedupe([*self.active_files, *_clean_paths(files)]), MAX_LIST_ITEMS)

    def add_inspected_files(self, files: list[str]) -> None:
        self.inspected_files = _cap(_dedupe([*self.inspected_files, *_clean_paths(files)]), MAX_LIST_ITEMS)

    def add_related_files(self, key: str, files: list[str]) -> None:
        clean_key = str(key or "workspace")[:160]
        self.related_files[clean_key] = _cap(
            _dedupe([*self.related_files.get(clean_key, []), *_clean_paths(files)]),
            MAX_LIST_ITEMS,
        )
        self.related_files = _compact_dict_lists(self.related_files)

    def record_repo_map(self, payload: dict[str, Any]) -> None:
        focus = str(payload.get("focus") or "workspace")
        related = _string_list(payload.get("related_files"))
        tests = _string_list(payload.get("test_files"))
        active = _string_list(payload.get("active_files"))
        self.add_active_files(active)
        self.add_inspected_files([*related[:20], *tests[:20], *_string_list(payload.get("key_files"))[:20]])
        self.add_related_files(focus, [*related, *tests])
        dependency_map = payload.get("dependency_map")
        if isinstance(dependency_map, dict):
            for path, deps in _dict_of_string_lists(dependency_map).items():
                self.dependency_map[path] = _cap(
                    _dedupe([*self.dependency_map.get(path, []), *deps]),
                    MAX_LIST_ITEMS,
                )
        reverse_map = payload.get("reverse_dependency_map")
        if isinstance(reverse_map, dict):
            self.repository_summary["reverse_dependency_map"] = _dict_of_string_lists(reverse_map)
        symbol_index = payload.get("symbol_index")
        if isinstance(symbol_index, dict):
            self.repository_summary["symbol_index"] = _compact_dict(symbol_index)
        self.repository_summary = _compact_dict(
            {
                **self.repository_summary,
                "last_focus": focus,
                "key_files": _string_list(payload.get("key_files"))[:40],
                "search_hints": _string_list(payload.get("search_hints"))[:20],
                "validation_targets": _string_list(payload.get("validation_targets"))[:20],
            }
        )
        self.execution_plan.record_files_for_active([*related, *tests])
        self.execution_plan.record_validation_targets_for_active(_string_list(payload.get("validation_targets")))
        self.compact()

    def record_tool_result(self, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        if tool_name == "read_file" and isinstance(payload.get("path"), str):
            self.execution_plan.activate_kind("inspect")
            self.add_inspected_files([payload["path"]])
            if result.get("ok") is not False:
                self.execution_plan.mark_active_completed()
        elif tool_name == "list_files" and isinstance(payload.get("files"), list):
            self.execution_plan.activate_kind("inspect")
            paths = [str(item.get("path")) for item in payload["files"] if isinstance(item, dict)]
            self.add_inspected_files(paths[:20])
            if result.get("ok") is not False:
                self.execution_plan.mark_active_completed()
        elif tool_name == "search_files" and isinstance(payload.get("matches"), list):
            self.execution_plan.activate_kind("inspect")
            paths = [str(item.get("path")) for item in payload["matches"] if isinstance(item, dict)]
            self.add_inspected_files(paths[:30])
            if result.get("ok") is not False:
                self.execution_plan.mark_active_completed()
        elif tool_name == "repo_map":
            self.execution_plan.activate_kind("inspect")
            self.record_repo_map(payload)
            if result.get("ok") is not False:
                self.execution_plan.mark_active_completed()
        elif tool_name in {"write_file", "replace_in_file", "apply_patch"}:
            active = self.execution_plan.active()
            if not (active and "-repair" in active.id and active.status == "active"):
                self.execution_plan.activate_kind("edit")
            changed = _changed_files(tool_name, result) or _string_list(result.get("affected_files"))
            self.add_related_files("recent_edits", changed)
            self.execution_plan.record_files_for_active(changed)
            summary = _edit_summary(payload, args)
            result_summary = result.get("summary")
            if isinstance(result_summary, str) and result_summary.strip():
                summary = result_summary.strip()[:240]
            self.planned_edits = _cap(
                [
                    *self.planned_edits,
                    {
                        "tool": tool_name,
                        "files": changed,
                        "summary": summary,
                        "status": _edit_status(result),
                    },
                ],
                MAX_HISTORY_ITEMS,
            )
            if result.get("approval_required"):
                self.execution_plan.mark_active_blocked(reason="Waiting for edit approval.")
            elif result.get("edit_policy_feedback"):
                self.execution_plan.mark_active_blocked(reason="Edit policy requires a grouped apply_patch.")
            elif result.get("ok") is False:
                self.execution_plan.mark_active_failed(repair_strategy=str(result.get("error") or "Retry with apply_patch."))
            elif result.get("validation", {}).get("ok") is False:
                self.execution_plan.mark_active_completed()
            else:
                self.execution_plan.mark_active_completed()
        validation = result.get("validation")
        if isinstance(validation, dict):
            self.record_validation(validation)
        repair = result.get("repair")
        if isinstance(repair, dict):
            self.record_repair(repair)
        self.compact()

    def record_validation(self, validation: dict[str, Any]) -> None:
        commands = [
            str(check.get("command"))
            for check in validation.get("checks", [])
            if isinstance(check, dict) and check.get("command")
        ]
        self.planned_validations = _cap(
            _dedupe([*self.planned_validations, *commands]),
            MAX_LIST_ITEMS,
        )
        self.execution_plan.activate_kind("validate")
        self.execution_plan.record_files_for_active(_string_list(validation.get("changed_files")))
        self.execution_plan.record_validation_targets_for_active(_string_list(validation.get("validation_targets")))
        self.validation_history = _cap(
            [
                *self.validation_history,
                {
                    "ok": validation.get("ok"),
                    "mode": validation.get("mode"),
                    "execution_node": validation.get("execution_node"),
                    "changed_files": _string_list(validation.get("changed_files")),
                    "validation_targets": _string_list(validation.get("validation_targets")),
                    "failed_categories": _string_list(validation.get("failed_categories")),
                    "checks": _compact_checks(validation.get("checks")),
                },
            ],
            MAX_HISTORY_ITEMS,
        )
        if validation.get("ok") is False:
            self.execution_plan.mark_active_failed(repair_strategy="Repair failed validation with minimal grouped apply_patch.")
        else:
            self.execution_plan.mark_active_completed()

    def record_repair(self, repair: dict[str, Any]) -> None:
        self.repair_history = _cap([*self.repair_history, dict(repair)], MAX_HISTORY_ITEMS)
        active = self.execution_plan.active()
        dependency = active.id if active else None
        self.execution_plan.add_repair_node(
            f"Repair {repair.get('kind', 'workspace issue')} attempt {repair.get('attempt', '')}".strip(),
            dependencies=[dependency] if dependency else [],
            strategy=str(repair.get("strategy") or "Apply the smallest safe repair."),
        )

    def record_approval(self, approval: dict[str, Any]) -> None:
        self.approval_history = _cap([*self.approval_history, dict(approval)], MAX_HISTORY_ITEMS)
        self.execution_plan.activate_kind("edit")
        self.execution_plan.record_files_for_active(_string_list(approval.get("affected_files")))
        self.execution_plan.mark_active_blocked(reason="Waiting for approval.")


def reasoning_state_message(state: WorkspaceReasoningState) -> str:
    return (
        "PERSISTENT WORKSPACE REASONING STATE:\n"
        f"{_json_dumps(state.to_dict())}\n\n"
        "Keep this state current mentally. Use repo_map/read/search before edits when context is incomplete, "
        "advance the active execution node, batch related edits into one grouped apply_patch, "
        "and continue unfinished or blocked execution nodes after approval, repair, or failover."
    )


def _reasoning_state_from_raw(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    runtime = raw.get("agent_hub_runtime")
    if isinstance(runtime, dict) and isinstance(runtime.get("reasoning_state"), dict):
        return runtime["reasoning_state"]
    hub = raw.get("agent_hub")
    if isinstance(hub, dict) and isinstance(hub.get("reasoning_state"), dict):
        return hub["reasoning_state"]
    return None


def _objectives_from_request(request: HubRequest) -> list[str]:
    text = "\n".join(
        str(part)
        for part in [
            request.task,
            request.context,
            *[
                message.get("content")
                for message in request.messages
                if isinstance(message.get("content"), str)
            ],
        ]
        if part
    )
    lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
    if lines:
        return _cap(lines, 8)
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    return [" ".join(words[:24])] if words else []


def _changed_files(tool_name: str, result: dict[str, Any]) -> list[str]:
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    if tool_name == "apply_patch" and isinstance(payload.get("paths"), list):
        return _string_list(payload["paths"])
    if isinstance(payload.get("path"), str):
        return [payload["path"]]
    return []


def _edit_summary(payload: dict[str, Any], args: dict[str, Any]) -> str:
    for key in ("summary", "path"):
        value = payload.get(key) or args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    return "workspace edit"


def _edit_status(result: dict[str, Any]) -> str:
    if result.get("approval_required"):
        return "pending_approval"
    if result.get("edit_policy_feedback"):
        return "policy_feedback"
    if result.get("ok") is False:
        return "failed"
    return "applied"


def _compact_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    checks: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        checks.append(
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "failure_category": item.get("failure_category"),
                "command": item.get("command"),
                "returncode": item.get("returncode"),
                "ok": item.get("ok"),
            }
        )
    return checks


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:300] for item in value if isinstance(item, str) and item.strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_compact_dict(item) for item in value if isinstance(item, dict)][:MAX_HISTORY_ITEMS]


def _dict_of_string_lists(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, items in list(value.items())[:MAX_DICT_KEYS]:
        result[str(key)[:160]] = _string_list(items)[:MAX_LIST_ITEMS]
    return result


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, item in list(value.items())[:MAX_DICT_KEYS]:
        clean_key = str(key)[:160]
        if isinstance(item, str):
            compact[clean_key] = item[:1000]
        elif isinstance(item, list):
            compact[clean_key] = item[:MAX_LIST_ITEMS]
        elif isinstance(item, dict):
            compact[clean_key] = _compact_dict(item)
        elif item is None or isinstance(item, (bool, int, float)):
            compact[clean_key] = item
        else:
            compact[clean_key] = str(item)[:1000]
    return compact


def _compact_dict_lists(value: dict[str, list[str]]) -> dict[str, list[str]]:
    return {
        key: _cap(_dedupe(items), MAX_LIST_ITEMS)
        for key, items in list(value.items())[-MAX_DICT_KEYS:]
        if items
    }


def _clean_paths(paths: list[str]) -> list[str]:
    return [path.replace("\\", "/") for path in paths if path and path != "."]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _cap(values: list[Any], maximum: int) -> list[Any]:
    return values[-maximum:]


def _execution_status(value: Any) -> str:
    status = str(value or "pending").strip().lower()
    if status in {"pending", "active", "completed", "failed", "blocked"}:
        return status
    return "pending"


def _risk_value(value: Any) -> str:
    risk = str(value or "low").strip().lower()
    if risk in {"low", "medium", "high"}:
        return risk
    return "low"


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "task"


def _higher_progress_status(left: str, right: str) -> str:
    order = {"pending": 0, "blocked": 1, "active": 2, "failed": 3, "completed": 4}
    return right if order.get(right, 0) >= order.get(left, 0) else left


def _higher_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    left = _risk_value(left)
    right = _risk_value(right)
    return right if order[right] >= order[left] else left


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, ensure_ascii=False)
