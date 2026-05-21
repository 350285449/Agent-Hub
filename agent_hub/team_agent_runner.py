from __future__ import annotations

import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .agent_runner import AgentEventSink, AgentRunner
from .agent_tools import AgentToolbox, ShellPermissionCallback
from .config import AgentConfig, HubConfig, is_free_agent
from .models import FailoverEvent, HubRequest, HubResponse
from .payloads import content_to_text, request_text
from .router import AgentRouter, RouterError


TEAM_ROLES = ("planner", "researcher", "coder", "reviewer", "fixer", "finalizer")
READ_ONLY_TOOLS = ["list_files", "read_file", "search_files", "run_command"]
EDIT_TOOLS = ["list_files", "read_file", "search_files", "write_file", "replace_in_file", "run_command"]


class TeamAgentRunner:
    """Coordinate several routed models around the existing workspace agent loop."""

    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    def run(
        self,
        request: HubRequest,
        event_sink: AgentEventSink | None = None,
        shell_permission_callback: ShellPermissionCallback | None = None,
    ) -> HubResponse:
        toolbox = AgentToolbox(self.config, request)
        failover: list[FailoverEvent] = []
        phases: list[dict[str, Any]] = []

        _emit(
            event_sink,
            "team_started",
            message="Started group-agent workflow.",
            workspace=str(toolbox.root),
        )

        plan_candidates = _request_int(request, "plan_candidates", default=1, minimum=1, maximum=5)
        plans = self._propose_plans(request, toolbox, plan_candidates, event_sink)
        failover.extend(event for plan in plans for event in plan["response"].failover)
        selected_plan = select_best_plan([plan["text"] for plan in plans], request, toolbox.root)
        phases.append(
            {
                "role": "planner",
                "candidates": [
                    {"agent": plan["response"].agent, "text": plan["text"], "score": plan["score"]}
                    for plan in plans
                ],
                "selected_plan": selected_plan,
            }
        )

        researcher = self._run_researcher(
            request,
            toolbox,
            selected_plan,
            event_sink,
            shell_permission_callback,
        )
        failover.extend(researcher.failover)
        phases.append({"role": "researcher", "agent": researcher.agent, "text": researcher.text})

        coder = self._run_coder(
            request,
            selected_plan,
            researcher.text,
            event_sink,
            shell_permission_callback,
        )
        failover.extend(coder.failover)
        phases.append(_phase_from_agent_response("coder", coder))

        review_context = _review_context(request, selected_plan, researcher.text, coder)
        reviewer = self._role_call(
            request,
            role="reviewer",
            prompt=review_context,
            event_sink=event_sink,
        )
        failover.extend(reviewer.failover)
        phases.append({"role": "reviewer", "agent": reviewer.agent, "text": reviewer.text})

        fixer: HubResponse | None = None
        if _review_requests_fixes(reviewer.text):
            fixer = self._run_fixer(
                request,
                selected_plan,
                reviewer.text,
                event_sink,
                shell_permission_callback,
            )
            failover.extend(fixer.failover)
            phases.append(_phase_from_agent_response("fixer", fixer))

        finalizer_prompt = _finalizer_prompt(
            request=request,
            plan=selected_plan,
            research=researcher.text,
            coder=coder,
            reviewer=reviewer,
            fixer=fixer,
        )
        finalizer = self._role_call(
            request,
            role="finalizer",
            prompt=finalizer_prompt,
            event_sink=event_sink,
        )
        failover.extend(finalizer.failover)

        raw = dict(finalizer.raw)
        existing_metadata = raw.get("agent_hub")
        metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        raw["agent_hub"] = {
            **metadata,
            "mode": "group-agent",
            "workspace": str(toolbox.root),
            "phases": phases,
            "finalizer_agent": finalizer.agent,
        }
        response = HubResponse(
            request_id=finalizer.request_id,
            session_id=request.session_id,
            agent=finalizer.agent,
            provider=finalizer.provider,
            model=finalizer.model,
            public_model=finalizer.public_model,
            text=finalizer.text,
            usage=finalizer.usage,
            raw=raw,
            finish_reason=finalizer.finish_reason,
            failover=failover,
            citations=finalizer.citations,
            search_results=finalizer.search_results,
            images=finalizer.images,
            related_questions=finalizer.related_questions,
        )
        if request.record_session:
            self.router.session_store.record_turn(request, response)
        _emit(event_sink, "team_final", message="Group-agent workflow completed.")
        return response

    def _propose_plans(
        self,
        request: HubRequest,
        toolbox: AgentToolbox,
        count: int,
        event_sink: AgentEventSink | None,
    ) -> list[dict[str, Any]]:
        agents = self._role_agents("planner", request)[:count]
        if not agents:
            agents = self._role_agents("finalizer", request)[:1]
        plans: list[dict[str, Any]] = []
        for index, agent in enumerate(agents, start=1):
            _emit(
                event_sink,
                "team_role_started",
                message=f"Planner candidate {index}: asking {agent.name} for a plan.",
                role="planner",
                agent=agent.name,
            )
            response = self._role_call(
                request,
                role="planner",
                prompt=_planner_prompt(request, toolbox.root),
                preferred_agent=agent.name,
                event_sink=event_sink,
            )
            score = score_plan(response.text, request, toolbox.root)
            plans.append({"response": response, "text": response.text, "score": score})
        if not plans:
            raise RouterError("No planner agent could produce a plan")
        return sorted(plans, key=lambda item: item["score"], reverse=True)

    def _run_researcher(
        self,
        request: HubRequest,
        toolbox: AgentToolbox,
        plan: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
    ) -> HubResponse:
        prompt = _researcher_prompt(request, toolbox.root, plan)
        return AgentRunner(self.config, self.router).run(
            self._role_agent_request(
                request,
                role="researcher",
                prompt=prompt,
                allowed_tools=READ_ONLY_TOOLS,
                max_steps=_request_int(request, "researcher_max_steps", default=4, minimum=1, maximum=20),
                fast_write_finalize=False,
            ),
            event_sink=event_sink,
            shell_permission_callback=shell_permission_callback,
        )

    def _run_coder(
        self,
        request: HubRequest,
        plan: str,
        research: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
    ) -> HubResponse:
        prompt = _coder_prompt(request, plan, research)
        return AgentRunner(self.config, self.router).run(
            self._role_agent_request(
                request,
                role="coder",
                prompt=prompt,
                allowed_tools=EDIT_TOOLS,
                max_steps=_request_int(
                    request,
                    "coder_max_steps",
                    default=self.config.agent_max_steps,
                    minimum=1,
                    maximum=50,
                ),
                fast_write_finalize=True,
            ),
            event_sink=event_sink,
            shell_permission_callback=shell_permission_callback,
        )

    def _run_fixer(
        self,
        request: HubRequest,
        plan: str,
        review: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
    ) -> HubResponse:
        prompt = _fixer_prompt(request, plan, review)
        return AgentRunner(self.config, self.router).run(
            self._role_agent_request(
                request,
                role="fixer",
                prompt=prompt,
                allowed_tools=EDIT_TOOLS,
                max_steps=_request_int(request, "fixer_max_steps", default=6, minimum=1, maximum=30),
                fast_write_finalize=True,
            ),
            event_sink=event_sink,
            shell_permission_callback=shell_permission_callback,
        )

    def _role_call(
        self,
        request: HubRequest,
        *,
        role: str,
        prompt: str,
        preferred_agent: str | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> HubResponse:
        agent_name = preferred_agent or self._role_agent_name(role, request)
        _emit(
            event_sink,
            "team_role_started",
            message=f"{role.capitalize()} model request.",
            role=role,
            agent=agent_name,
        )
        response = self.router.route(
            replace(
                request,
                messages=[{"role": "user", "content": prompt}],
                preferred_agent=agent_name,
                use_session_history=False,
                record_session=False,
                stream=False,
                raw=_role_raw(request, role),
            )
        )
        _emit(
            event_sink,
            "team_role_finished",
            message=f"{role.capitalize()} response received from {response.agent}.",
            role=role,
            agent=response.agent,
            provider=response.provider,
            model=response.model,
        )
        return response

    def _role_agent_request(
        self,
        request: HubRequest,
        *,
        role: str,
        prompt: str,
        allowed_tools: list[str],
        max_steps: int,
        fast_write_finalize: bool,
    ) -> HubRequest:
        raw = _role_raw(request, role)
        raw["agent_hub_allowed_tools"] = allowed_tools
        raw["agent_max_steps"] = max_steps
        raw["fast_write_finalize"] = fast_write_finalize
        raw.setdefault("agent_hub", {})
        if isinstance(raw["agent_hub"], dict):
            raw["agent_hub"]["allowed_tools"] = allowed_tools
        return replace(
            request,
            messages=[{"role": "user", "content": prompt}],
            preferred_agent=self._role_agent_name(role, request),
            use_session_history=False,
            record_session=False,
            stream=False,
            raw=raw,
        )

    def _role_agent_name(self, role: str, request: HubRequest) -> str | None:
        agents = self._role_agents(role, request)
        return agents[0].name if agents else None

    def _role_agents(self, role: str, request: HubRequest) -> list[AgentConfig]:
        configured = self.config.group_roles.get(role)
        if configured and configured in self.config.agents and self.config.agents[configured].enabled:
            return [self.config.agents[configured]]

        route_names = _route_names(self.config, request)
        candidates = [
            self.config.agents[name]
            for name in route_names
            if name in self.config.agents and self.config.agents[name].enabled
        ]
        if self.config.free_only:
            candidates = [agent for agent in candidates if is_free_agent(agent)]
        return sorted(
            candidates,
            key=lambda agent: (-_role_score(agent, role), route_names.index(agent.name)),
        )


def score_plan(plan: str, request: HubRequest, root: Path) -> float:
    """Heuristic scoring for plan voting when no judge model is configured."""

    text = plan.lower()
    score = 0.0
    requested_paths = _requested_paths(request)
    for path in requested_paths:
        if path.lower() in text:
            score += 2.0
    if any(word in text for word in ("test", "verify", "run", "check")):
        score += 2.0
    if any(word in text for word in ("minimal", "targeted", "scoped", "preserve")):
        score += 1.0
    if any(word in text for word in ("read", "inspect", "search")):
        score += 1.0
    if "vscode-extension/backend" in text and "vscode-extension/backend" not in request_text(request).lower():
        score -= 4.0
    if any(bad in text for bad in ("rm -rf", "delete the repository", "rewrite everything", "../")):
        score -= 6.0

    for path in _path_like_tokens(plan):
        if path in requested_paths:
            continue
        candidate = (root / path).resolve()
        try:
            inside = candidate == root or candidate.is_relative_to(root)
        except ValueError:
            inside = False
        if not inside:
            score -= 3.0
        elif not candidate.exists() and "." in Path(path).name:
            score -= 0.5
    return score


def select_best_plan(plans: list[str], request: HubRequest, root: Path) -> str:
    if not plans:
        return "Inspect the workspace, make the requested change, review it, and verify when possible."
    return max(plans, key=lambda plan: score_plan(plan, request, root))


def _role_score(agent: AgentConfig, role: str) -> float:
    base = float(agent.priority or 0.0)
    coding = float(agent.coding_score or 0.0)
    reasoning = float(agent.reasoning_score or 0.0)
    speed = float(agent.speed_score or 0.0)
    context = min(1.0, float(agent.context_window or 0) / 128_000)
    tools = 0.2 if agent.supports_tools or agent.supports_function_calling else 0.0
    if role in {"coder", "fixer"}:
        return base + coding * 20 + reasoning * 5 + tools * 10
    if role in {"planner", "reviewer"}:
        return base + reasoning * 20 + coding * 5 + context * 5
    if role == "researcher":
        return base + context * 12 + reasoning * 8 + speed * 4 + tools * 8
    return base + reasoning * 8 + speed * 8 + coding * 4


def _route_names(config: HubConfig, request: HubRequest) -> list[str]:
    if request.route:
        for route in config.routes:
            if route.name == request.route:
                return route.agents
    text = request_text(request)
    for route in config.routes:
        if route.matches(text):
            return route.agents
    return config.default_route


def _role_raw(request: HubRequest, role: str) -> dict[str, Any]:
    raw = dict(request.raw or {})
    raw["team_agent_role"] = role
    raw["mode"] = "group-agent"
    return raw


def _planner_prompt(request: HubRequest, root: Path) -> str:
    return "\n".join(
        [
            "You are the planner in an Agent Hub coding team.",
            f"Workspace root: {root}",
            "Break the task into a concise, safe implementation plan.",
            "Prefer minimal scoped edits, mention likely files, and include verification.",
            "Avoid destructive rewrites and avoid duplicate workspace copies unless the user named them.",
            "",
            "Task:",
            request_text(request),
        ]
    )


def _researcher_prompt(request: HubRequest, root: Path, plan: str) -> str:
    return "\n".join(
        [
            "You are the researcher in an Agent Hub coding team.",
            f"Workspace root: {root}",
            "Use only read/search/list tools, and run safe inspection commands if useful.",
            "Gather concise repository context needed by the coder. Do not edit files.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            plan,
        ]
    )


def _coder_prompt(request: HubRequest, plan: str, research: str) -> str:
    return "\n".join(
        [
            "You are the coder in an Agent Hub coding team.",
            "Confirm the workspace root and target path before editing.",
            "Inspect files before editing, keep changes scoped, and verify when possible.",
            "Use write_file or replace_in_file only for the requested workspace files.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            plan,
            "",
            "Research context:",
            research,
        ]
    )


def _review_context(request: HubRequest, plan: str, research: str, coder: HubResponse) -> str:
    return "\n".join(
        [
            "You are the reviewer in an Agent Hub coding team.",
            "Review the coder's result for correctness, scope, style, safety, and missing tests.",
            "Return either 'No blocking issues' or a concise list of required fixes.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            plan,
            "",
            "Research context:",
            research,
            "",
            "Coder result:",
            coder.text,
            "",
            "Coder trace:",
            _trace_summary(coder),
        ]
    )


def _fixer_prompt(request: HubRequest, plan: str, review: str) -> str:
    return "\n".join(
        [
            "You are the fixer in an Agent Hub coding team.",
            "Apply only the review fixes that are necessary for the user's task.",
            "Inspect files before editing and verify when possible.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            plan,
            "",
            "Review feedback:",
            review,
        ]
    )


def _finalizer_prompt(
    *,
    request: HubRequest,
    plan: str,
    research: str,
    coder: HubResponse,
    reviewer: HubResponse,
    fixer: HubResponse | None,
) -> str:
    return "\n".join(
        [
            "You are the finalizer in an Agent Hub coding team.",
            "Summarize changed files, verification, failover, and any remaining risks in a concise final answer.",
            "",
            "Task:",
            request_text(request),
            "",
            "Plan:",
            plan,
            "",
            "Research:",
            research,
            "",
            "Coder result:",
            coder.text,
            "",
            "Reviewer result:",
            reviewer.text,
            "",
            "Fixer result:",
            fixer.text if fixer else "No fixer pass was needed.",
            "",
            "Tool traces:",
            _trace_summary(fixer or coder),
        ]
    )


def _trace_summary(response: HubResponse) -> str:
    metadata = response.raw.get("agent_hub") if isinstance(response.raw, dict) else None
    steps = metadata.get("steps") if isinstance(metadata, dict) else None
    if not isinstance(steps, list):
        return "No tool trace available."
    lines: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        path = payload.get("path") if isinstance(payload, dict) else None
        status = "ok" if result.get("ok") is not False else "failed"
        suffix = f" {path}" if path else ""
        lines.append(f"- step {step.get('step')}: {step.get('tool')} {status}{suffix}")
    return "\n".join(lines) if lines else "No tool trace available."


def _phase_from_agent_response(role: str, response: HubResponse) -> dict[str, Any]:
    return {
        "role": role,
        "agent": response.agent,
        "text": response.text,
        "trace": response.raw.get("agent_hub", {}).get("steps", [])
        if isinstance(response.raw.get("agent_hub"), dict)
        else [],
    }


def _review_requests_fixes(text: str) -> bool:
    lowered = text.lower()
    if "no blocking issues" in lowered or "no required fixes" in lowered:
        return False
    return any(marker in lowered for marker in ("required fix", "blocking", "must fix", "bug", "regression"))


def _requested_paths(request: HubRequest) -> set[str]:
    text = request_text(request)
    return {token.replace("\\", "/") for token in _path_like_tokens(text)}


def _path_like_tokens(text: str) -> set[str]:
    tokens = re.findall(r"(?<![\w.-])(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|json|md|toml|yml|yaml|txt)", text)
    return {token.strip("`'\".,;:()[]{}").replace("\\", "/") for token in tokens if token}


def _request_int(
    request: HubRequest,
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.raw or {}
    group = raw.get("group_agent")
    value = group.get(key) if isinstance(group, dict) and key in group else raw.get(key)
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _emit(event_sink: AgentEventSink | None, event_type: str, **data: Any) -> None:
    if event_sink is None:
        return
    try:
        event_sink({"type": event_type, **data})
    except Exception:
        return
