from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from .agent_runner import AgentEventSink, AgentRunner
from .agent_tools import AgentToolbox, ShellPermissionCallback
from .config import AgentConfig, HubConfig, is_free_agent
from .models import FailoverEvent, HubRequest, HubResponse
from .payloads import content_to_text, request_text
from .reasoning import WorkspaceReasoningState
from .core.router import AgentRouter, RouterError


TEAM_ROLES = (
    "planner",
    "researcher",
    "worker_candidate",
    "judge",
    "coder",
    "reviewer",
    "validator",
    "repair",
    "fixer",
    "finalizer",
)
READ_ONLY_TOOLS = ["list_files", "read_file", "search_files", "repo_map", "run_command"]
EDIT_TOOLS = [
    "list_files",
    "read_file",
    "search_files",
    "repo_map",
    "write_file",
    "replace_in_file",
    "apply_patch",
    "run_command",
]


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
        session_data = self.router.session_store.load(request.session_id)
        reasoning_state = WorkspaceReasoningState.for_request(request, session_data=session_data)
        reasoning_state.add_active_files(_active_files_from_toolbox(toolbox))
        failover: list[FailoverEvent] = []
        phases: list[dict[str, Any]] = []

        _emit(
            event_sink,
            "team_started",
            message="Started group-agent workflow.",
            workspace=str(toolbox.root),
        )

        plan_candidates = _request_int(request, "plan_candidates", default=1, minimum=1, maximum=5)
        plans = self._propose_plans(request, toolbox, plan_candidates, event_sink, reasoning_state)
        failover.extend(event for plan in plans for event in plan["response"].failover)
        selected_plan = select_best_plan([plan["text"] for plan in plans], request, toolbox.root)
        reasoning_state.repository_summary = {
            **reasoning_state.repository_summary,
            "selected_team_plan": selected_plan[:1000],
        }
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
            reasoning_state,
        )
        failover.extend(researcher.failover)
        _merge_response_reasoning(reasoning_state, researcher)
        phases.append({"role": "researcher", "agent": researcher.agent, "text": researcher.text})

        worker_plan = ""
        worker_candidate_count = _request_int(
            request,
            "worker_candidates",
            default=1,
            minimum=1,
            maximum=5,
        )
        if worker_candidate_count > 1:
            judged_workers = self._judge_worker_candidates(
                request,
                selected_plan,
                researcher.text,
                worker_candidate_count,
                event_sink,
                reasoning_state,
            )
            failover.extend(
                event
                for candidate in judged_workers["candidates"]
                for event in candidate["response"].failover
            )
            if judged_workers.get("judge_response") is not None:
                failover.extend(judged_workers["judge_response"].failover)
            worker_plan = judged_workers["selected_text"]
            phases.append(
                {
                    "role": "worker_judge",
                    "judge": judged_workers["judge"],
                    "selected_index": judged_workers["selected_index"],
                    "selected_agent": judged_workers["selected_agent"],
                    "candidates": [
                        {
                            "index": candidate["index"],
                            "agent": candidate["response"].agent,
                            "score": candidate["score"],
                            "text": candidate["text"],
                        }
                        for candidate in judged_workers["candidates"]
                    ],
                    "text": worker_plan,
                }
            )

        coder = self._run_coder(
            request,
            selected_plan,
            researcher.text,
            worker_plan,
            event_sink,
            shell_permission_callback,
            reasoning_state,
        )
        failover.extend(coder.failover)
        _merge_response_reasoning(reasoning_state, coder)
        phases.append(_phase_from_agent_response("coder", coder))

        validator: HubResponse | None = None
        if self._has_role("validator", request) or _request_bool(request, "enable_validator_agent", default=False):
            validator = self._role_call(
                request,
                role="validator",
                prompt=_validator_prompt(request, selected_plan, researcher.text, coder),
                event_sink=event_sink,
                reasoning_state=reasoning_state,
            )
            failover.extend(validator.failover)
            _merge_response_reasoning(reasoning_state, validator)
            phases.append({"role": "validator", "agent": validator.agent, "text": validator.text})

        review_context = _review_context(request, selected_plan, researcher.text, coder)
        reviewer = self._role_call(
            request,
            role="reviewer",
            prompt=review_context,
            event_sink=event_sink,
            reasoning_state=reasoning_state,
        )
        failover.extend(reviewer.failover)
        _merge_response_reasoning(reasoning_state, reviewer)
        phases.append({"role": "reviewer", "agent": reviewer.agent, "text": reviewer.text})

        fixer: HubResponse | None = None
        repair_text = "\n".join(
            text
            for text in [
                reviewer.text,
                validator.text if validator and _review_requests_fixes(validator.text) else "",
            ]
            if text
        )
        if _review_requests_fixes(repair_text):
            fixer = self._run_fixer(
                request,
                selected_plan,
                repair_text,
                event_sink,
                shell_permission_callback,
                reasoning_state,
            )
            failover.extend(fixer.failover)
            _merge_response_reasoning(reasoning_state, fixer)
            phases.append(_phase_from_agent_response("fixer", fixer))

        finalizer_prompt = _finalizer_prompt(
            request=request,
            plan=selected_plan,
            research=researcher.text,
            coder=coder,
            reviewer=reviewer,
            validator=validator,
            fixer=fixer,
        )
        finalizer = self._role_call(
            request,
            role="finalizer",
            prompt=finalizer_prompt,
            event_sink=event_sink,
            reasoning_state=reasoning_state,
        )
        failover.extend(finalizer.failover)
        _merge_response_reasoning(reasoning_state, finalizer)

        raw = dict(finalizer.raw)
        existing_metadata = raw.get("agent_hub")
        metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        raw["agent_hub"] = {
            **metadata,
            "mode": "group-agent",
            "workspace": str(toolbox.root),
            "phases": phases,
            "finalizer_agent": finalizer.agent,
            "reasoning_state": reasoning_state.to_dict(),
            "execution_plan": reasoning_state.execution_plan.to_dict(),
            "confidence": _team_confidence(phases, finalizer),
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
        reasoning_state: WorkspaceReasoningState,
    ) -> list[dict[str, Any]]:
        agents = self._role_agents("planner", request)[:count]
        if not agents:
            agents = self._role_agents("finalizer", request)[:1]
        plans: list[dict[str, Any]] = []
        if len(agents) == 1:
            plans.append(self._planner_candidate(
                request, toolbox, agents[0], 1, event_sink, reasoning_state
            ))
        else:
            with ThreadPoolExecutor(max_workers=min(len(agents), count)) as executor:
                futures = {
                    executor.submit(
                        self._planner_candidate,
                        request,
                        toolbox,
                        agent,
                        index,
                        event_sink,
                        reasoning_state,
                    ): agent
                    for index, agent in enumerate(agents, start=1)
                }
                for future in as_completed(futures):
                    plans.append(future.result())
        if not plans:
            raise RouterError("No planner agent could produce a plan")
        return sorted(plans, key=lambda item: item["score"], reverse=True)

    def _planner_candidate(
        self,
        request: HubRequest,
        toolbox: AgentToolbox,
        agent: AgentConfig,
        index: int,
        event_sink: AgentEventSink | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> dict[str, Any]:
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
            reasoning_state=reasoning_state,
        )
        score = score_plan(response.text, request, toolbox.root)
        return {
            "response": response,
            "text": _compact_phase_text(response.text),
            "score": score,
            "confidence": _score_to_confidence(score),
        }

    def _run_researcher(
        self,
        request: HubRequest,
        toolbox: AgentToolbox,
        plan: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> HubResponse:
        prompt = _researcher_prompt(request, toolbox.root, plan)
        _emit_context_inherited(event_sink, "researcher", reasoning_state)
        return AgentRunner(self.config, self.router).run(
            self._role_agent_request(
                request,
                role="researcher",
                prompt=prompt,
                allowed_tools=READ_ONLY_TOOLS,
                max_steps=_request_int(request, "researcher_max_steps", default=4, minimum=1, maximum=20),
                fast_write_finalize=False,
                reasoning_state=reasoning_state,
            ),
            event_sink=event_sink,
            shell_permission_callback=shell_permission_callback,
        )

    def _run_coder(
        self,
        request: HubRequest,
        plan: str,
        research: str,
        worker_plan: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> HubResponse:
        prompt = _coder_prompt(request, plan, research, worker_plan)
        _emit_context_inherited(event_sink, "coder", reasoning_state)
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
                fast_write_finalize=_request_bool(
                    request,
                    "fast_write_finalize",
                    default=self.config.fast_write_finalize,
                ),
                reasoning_state=reasoning_state,
            ),
            event_sink=event_sink,
            shell_permission_callback=shell_permission_callback,
        )

    def _judge_worker_candidates(
        self,
        request: HubRequest,
        plan: str,
        research: str,
        count: int,
        event_sink: AgentEventSink | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> dict[str, Any]:
        agents = self._tournament_candidate_agents(request)[:count]
        if not agents:
            agents = self._role_agents("finalizer", request)[:1]
        candidates: list[dict[str, Any]] = []
        if len(agents) == 1:
            candidates.append(
                self._worker_candidate(
                    request,
                    plan,
                    research,
                    agents[0],
                    1,
                    event_sink,
                    reasoning_state,
                )
            )
        else:
            with ThreadPoolExecutor(max_workers=min(len(agents), count)) as executor:
                futures = {
                    executor.submit(
                        self._worker_candidate,
                        request,
                        plan,
                        research,
                        agent,
                        index,
                        event_sink,
                        reasoning_state,
                    ): agent
                    for index, agent in enumerate(agents, start=1)
                }
                for future in as_completed(futures):
                    candidates.append(future.result())
        candidates = sorted(candidates, key=lambda item: item["index"])
        if not candidates:
            return {
                "judge": "none",
                "judge_response": None,
                "selected_index": 1,
                "selected_agent": "",
                "selected_text": "Inspect the workspace, make the requested change, and verify.",
                "candidates": [],
            }
        selected_index = select_best_worker_candidate(
            [candidate["text"] for candidate in candidates],
            request,
        )
        judge_response: HubResponse | None = None
        judge = "heuristic"
        if self._has_role("judge", request):
            judge_response = self._role_call(
                request,
                role="judge",
                prompt=_judge_prompt(request, plan, research, candidates),
                event_sink=event_sink,
                reasoning_state=reasoning_state,
            )
            parsed_index = _selected_candidate_index(judge_response.text, len(candidates))
            if parsed_index is not None:
                selected_index = parsed_index
                judge = judge_response.agent
        selected = candidates[max(0, min(selected_index - 1, len(candidates) - 1))]
        return {
            "judge": judge,
            "judge_response": judge_response,
            "selected_index": selected["index"],
            "selected_agent": selected["response"].agent,
            "selected_text": selected["text"],
            "candidates": candidates,
        }

    def _worker_candidate(
        self,
        request: HubRequest,
        plan: str,
        research: str,
        agent: AgentConfig,
        index: int,
        event_sink: AgentEventSink | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> dict[str, Any]:
        _emit(
            event_sink,
            "team_role_started",
            message=f"Worker candidate {index}: asking {agent.name} for an execution proposal.",
            role="worker_candidate",
            agent=agent.name,
        )
        response = self._role_call(
            request,
            role="worker_candidate",
            prompt=_worker_candidate_prompt(request, plan, research, index),
            preferred_agent=agent.name,
            event_sink=event_sink,
            reasoning_state=reasoning_state,
        )
        text = _compact_phase_text(response.text)
        return {
            "index": index,
            "response": response,
            "text": text,
            "score": score_worker_candidate(text, request),
        }

    def _run_fixer(
        self,
        request: HubRequest,
        plan: str,
        review: str,
        event_sink: AgentEventSink | None,
        shell_permission_callback: ShellPermissionCallback | None,
        reasoning_state: WorkspaceReasoningState,
    ) -> HubResponse:
        prompt = _fixer_prompt(request, plan, review)
        role = "repair" if self._has_role("repair", request) else "fixer"
        _emit_context_inherited(event_sink, role, reasoning_state)
        return AgentRunner(self.config, self.router).run(
            self._role_agent_request(
                request,
                role=role,
                prompt=prompt,
                allowed_tools=EDIT_TOOLS,
                max_steps=_request_int(request, "fixer_max_steps", default=6, minimum=1, maximum=30),
                fast_write_finalize=_request_bool(
                    request,
                    "fast_write_finalize",
                    default=self.config.fast_write_finalize,
                ),
                reasoning_state=reasoning_state,
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
        reasoning_state: WorkspaceReasoningState | None = None,
    ) -> HubResponse:
        agent_name = preferred_agent or self._role_agent_name(role, request)
        _emit(
            event_sink,
            "team_role_started",
            message=f"{role.capitalize()} model request.",
            role=role,
            agent=agent_name,
        )
        if reasoning_state is not None and role != "planner":
            _emit_context_inherited(event_sink, role, reasoning_state)
        response = self.router.route(
            replace(
                request,
                messages=[{"role": "user", "content": _with_reasoning_context(prompt, reasoning_state)}],
                preferred_agent=agent_name,
                use_session_history=False,
                record_session=False,
                stream=False,
                raw=_role_raw(request, role, reasoning_state),
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
            failover=[event.to_dict() for event in response.failover],
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
        reasoning_state: WorkspaceReasoningState,
    ) -> HubRequest:
        raw = _role_raw(request, role, reasoning_state)
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

    def _tournament_candidate_agents(self, request: HubRequest) -> list[AgentConfig]:
        agents = self._role_agents("coder", request)
        cheap = [agent for agent in agents if is_free_agent(agent)]
        return cheap or agents

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

    def _has_role(self, role: str, request: HubRequest) -> bool:
        configured = self.config.group_roles.get(role)
        if configured and configured in self.config.agents and self.config.agents[configured].enabled:
            return True
        raw = request.raw or {}
        group = raw.get("group_agent")
        enabled_roles = group.get("enabled_roles") if isinstance(group, dict) else None
        return isinstance(enabled_roles, list) and role in enabled_roles


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


def score_worker_candidate(candidate: str, request: HubRequest) -> float:
    """Score non-editing worker proposals before the real coder runs."""

    text = candidate.lower()
    score = 0.0
    requested_paths = _requested_paths(request)
    for path in requested_paths:
        if path.lower() in text:
            score += 2.0
    if any(word in text for word in ("test", "verify", "run", "check")):
        score += 2.0
    if any(word in text for word in ("minimal", "targeted", "scoped", "preserve")):
        score += 1.5
    if any(word in text for word in ("risk", "rollback", "compatib", "regression")):
        score += 1.0
    if any(word in text for word in ("read", "inspect", "search")):
        score += 0.75
    if any(bad in text for bad in ("rm -rf", "delete the repository", "rewrite everything", "../")):
        score -= 8.0
    if "do not test" in text or "skip validation" in text:
        score -= 3.0
    return score


def select_best_worker_candidate(candidates: list[str], request: HubRequest) -> int:
    if not candidates:
        return 1
    best_index = max(
        range(len(candidates)),
        key=lambda index: score_worker_candidate(candidates[index], request),
    )
    return best_index + 1


def _role_score(agent: AgentConfig, role: str) -> float:
    base = float(agent.priority or 0.0)
    coding = float(agent.coding_score or 0.0)
    reasoning = float(agent.reasoning_score or 0.0)
    speed = float(agent.speed_score or 0.0)
    context = min(1.0, float(agent.context_window or 0) / 128_000)
    tools = 0.2 if agent.supports_tools or agent.supports_function_calling else 0.0
    if role in {"coder", "fixer", "worker_candidate"}:
        return base + coding * 20 + reasoning * 5 + tools * 10
    if role in {"planner", "reviewer", "judge"}:
        return base + reasoning * 20 + coding * 5 + context * 5
    if role == "validator":
        return base + reasoning * 16 + coding * 8 + tools * 6 + context * 3
    if role == "researcher":
        return base + context * 12 + reasoning * 8 + speed * 4 + tools * 8
    if role == "repair":
        return base + coding * 18 + reasoning * 8 + tools * 10
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


def _role_raw(
    request: HubRequest,
    role: str,
    reasoning_state: WorkspaceReasoningState | None = None,
) -> dict[str, Any]:
    raw = dict(request.raw or {})
    raw["team_agent_role"] = role
    raw["mode"] = "group-agent"
    if reasoning_state is not None:
        state = reasoning_state.to_dict()
        runtime = raw.get("agent_hub_runtime")
        runtime = dict(runtime) if isinstance(runtime, dict) else {}
        runtime["reasoning_state"] = state
        raw["agent_hub_runtime"] = runtime
        hub = raw.get("agent_hub")
        hub = dict(hub) if isinstance(hub, dict) else {}
        hub["reasoning_state"] = state
        raw["agent_hub"] = hub
    return raw


def _with_reasoning_context(
    prompt: str,
    reasoning_state: WorkspaceReasoningState | None,
) -> str:
    if reasoning_state is None:
        return prompt
    return "\n".join(
        [
            prompt,
            "",
            "Shared workspace reasoning state:",
            json.dumps(reasoning_state.to_dict(), indent=2, ensure_ascii=False),
        ]
    )


def _planner_prompt(request: HubRequest, root: Path) -> str:
    return "\n".join(
        [
            "You are the planner in an Agent Hub coding team.",
            f"Workspace root: {root}",
            "Break the task into concise execution objectives with dependencies, likely files, risk, and validation.",
            "Recommend concrete repository inspection targets, related files, impacted files, dependencies, and validation targets before coder edits begin.",
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
            "Expand the repository graph before the coder runs: use repo_map or search_files, then read target files and related tests/config/docs/dependencies. Do not edit files.",
            "Identify imports, related tests, configs, docs, validation targets, and dependency impact. Preserve inspected files, repository graph, and context score in the shared reasoning state.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            plan,
        ]
    )


def _coder_prompt(request: HubRequest, plan: str, research: str, worker_plan: str = "") -> str:
    parts = [
        "You are the coder in an Agent Hub coding team.",
        "Confirm the workspace root and target path before editing.",
        "Inspect files before editing, keep changes scoped, and verify when possible.",
        "Obey the context change bar using inherited repository graph, inspected files, related files, impacted files, and context score.",
        "Use one grouped apply_patch for related edits across implementation, tests, configs, docs, and dependency-aware fixes.",
        "Advance the active execution node; use write_file only for new/generated files and replace_in_file only for tiny isolated edits after the relevant context is inspected.",
        "",
        "Task:",
        request_text(request),
        "",
        "Selected plan:",
        plan,
    ]
    if worker_plan:
        parts.extend(
            [
                "",
                "Selected worker proposal:",
                worker_plan,
            ]
        )
    parts.extend(
        [
            "",
            "Research context:",
            research,
        ]
    )
    return "\n".join(parts)


def _worker_candidate_prompt(request: HubRequest, plan: str, research: str, index: int) -> str:
    return "\n".join(
        [
            "You are a worker candidate in an Agent Hub large-task team.",
            "Propose the best execution approach. Do not edit files, call tools, or claim work is complete.",
            "Name likely files, validation steps, risks, and the smallest safe implementation path.",
            f"Candidate index: {index}",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            _compact_phase_text(plan),
            "",
            "Research context:",
            _compact_phase_text(research),
        ]
    )


def _judge_prompt(
    request: HubRequest,
    plan: str,
    research: str,
    candidates: list[dict[str, Any]],
) -> str:
    lines = [
        "You are the judge in an Agent Hub large-task team.",
        "Pick the safest, most complete worker proposal. Prefer scoped changes, validation, and repository-specific detail.",
        "Return 'selected: N' with a short reason.",
        "",
        "Task:",
        request_text(request),
        "",
        "Selected plan:",
        _compact_phase_text(plan),
        "",
        "Research context:",
        _compact_phase_text(research),
    ]
    for candidate in candidates:
        lines.extend(
            [
                "",
                f"Candidate {candidate['index']} from {candidate['response'].agent}:",
                _compact_phase_text(candidate["text"]),
            ]
        )
    return "\n".join(lines)


def _review_context(request: HubRequest, plan: str, research: str, coder: HubResponse) -> str:
    return "\n".join(
        [
            "You are the reviewer in an Agent Hub coding team.",
            "Review the coder's result for correctness, scope, style, safety, and missing tests.",
            "Explicitly verify repository consistency, related file coverage, validation coverage, dependency impact, and grouped patch correctness.",
            "Reject edits against unread files, unread dependencies, implementation-only edits when related tests exist, and isolated edits for multi-file tasks.",
            "Return either 'No blocking issues' or a concise list of required fixes.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            _compact_phase_text(plan),
            "",
            "Research context:",
            _compact_phase_text(research),
            "",
            "Coder result:",
            _compact_phase_text(coder.text),
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
            "Repair the active failed execution node with the smallest grouped apply_patch that preserves prior successful work, repository graph continuity, and validation coverage.",
            "",
            "Task:",
            request_text(request),
            "",
            "Selected plan:",
            _compact_phase_text(plan),
            "",
            "Review feedback:",
            _compact_phase_text(review),
        ]
    )


def _validator_prompt(request: HubRequest, plan: str, research: str, coder: HubResponse) -> str:
    return "\n".join(
        [
            "You are the validator in an Agent Hub coding team.",
            "Validate the coder's result against the task, changed files, and known test targets. Do not edit files.",
            "Return 'Validation passed' or a concise list of failures and exact repair guidance.",
            "",
            "Task:",
            request_text(request),
            "",
            "Plan:",
            _compact_phase_text(plan),
            "",
            "Research memory:",
            _compact_phase_text(research),
            "",
            "Coder result:",
            _compact_phase_text(coder.text),
            "",
            "Tool trace:",
            _trace_summary(coder),
        ]
    )


def _finalizer_prompt(
    *,
    request: HubRequest,
    plan: str,
    research: str,
    coder: HubResponse,
    reviewer: HubResponse,
    validator: HubResponse | None,
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
            _compact_phase_text(plan),
            "",
            "Research:",
            _compact_phase_text(research),
            "",
            "Coder result:",
            _compact_phase_text(coder.text),
            "",
            "Reviewer result:",
            _compact_phase_text(reviewer.text),
            "",
            "Validator result:",
            _compact_phase_text(validator.text) if validator else "No validator pass was configured.",
            "",
            "Fixer result:",
            _compact_phase_text(fixer.text) if fixer else "No repair pass was needed.",
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
        "text": _compact_phase_text(response.text),
        "trace": response.raw.get("agent_hub", {}).get("steps", [])
        if isinstance(response.raw.get("agent_hub"), dict)
        else [],
    }


def _compact_phase_text(text: str, *, maximum: int = 2400) -> str:
    clean = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    if len(clean) <= maximum:
        return clean
    head = clean[: int(maximum * 0.65)].rstrip()
    tail = clean[-int(maximum * 0.25) :].lstrip()
    return f"{head}\n\n[compact: omitted {len(clean) - len(head) - len(tail)} chars]\n\n{tail}"


def _score_to_confidence(score: float) -> float:
    return round(max(0.0, min(1.0, 0.45 + (score / 20.0))), 3)


def _selected_candidate_index(text: str, maximum: int) -> int | None:
    match = re.search(r"\bselected\s*[:#-]?\s*(\d+)\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\bcandidate\s+(\d+)\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if 1 <= value <= maximum:
        return value
    return None


def _team_confidence(phases: list[dict[str, Any]], finalizer: HubResponse) -> dict[str, Any]:
    blocking_text = " ".join(str(phase.get("text") or "") for phase in phases).lower()
    penalties = sum(
        1
        for marker in ("blocking", "must fix", "failed", "regression")
        if marker in blocking_text
    )
    score = max(0.1, min(0.98, 0.82 - penalties * 0.12 + (0.04 if finalizer.text else 0.0)))
    return {
        "score": round(score, 3),
        "basis": "phase summaries, review/validation language, and finalizer completion",
    }


def _merge_response_reasoning(state: WorkspaceReasoningState, response: HubResponse) -> None:
    metadata = response.raw.get("agent_hub") if isinstance(response.raw, dict) else None
    value = metadata.get("reasoning_state") if isinstance(metadata, dict) else None
    if isinstance(value, dict):
        state.merge_from(WorkspaceReasoningState.from_dict(value, task_id=state.task_id))


def _active_files_from_toolbox(toolbox: AgentToolbox) -> list[str]:
    try:
        return [toolbox._relative(path) for path in toolbox._request_context_paths() if path.exists()]
    except Exception:
        return []


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


def _request_bool(request: HubRequest, key: str, *, default: bool) -> bool:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    value = hub_options.get(key) if isinstance(hub_options, dict) and key in hub_options else raw.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _emit(event_sink: AgentEventSink | None, event_type: str, **data: Any) -> None:
    if event_sink is None:
        return
    try:
        event_sink({"type": event_type, **data})
    except Exception:
        return


def _emit_context_inherited(
    event_sink: AgentEventSink | None,
    role: str,
    reasoning_state: WorkspaceReasoningState,
) -> None:
    graph_nodes = _repository_graph_nodes(reasoning_state)
    _emit(
        event_sink,
        "repository_context_inherited",
        message=f"{role.capitalize()} inherited repository context.",
        role=role,
        context_score=reasoning_state.context_score,
        inspected_files=reasoning_state.inspected_files[-20:],
        related_files_count=sum(len(files) for files in reasoning_state.related_files.values()),
        graph_node_count=len(graph_nodes),
        graph_edge_count=len(reasoning_state.dependency_edges),
        impacted_files=[path for files in reasoning_state.impacted_files.values() for path in files][:30],
    )


def _repository_graph_nodes(reasoning_state: WorkspaceReasoningState) -> list[str]:
    nodes: list[str] = []
    nodes.extend(reasoning_state.inspected_files)
    nodes.extend(reasoning_state.repository_summary_files())
    for edge in reasoning_state.dependency_edges:
        nodes.append(str(edge.get("source") or ""))
        nodes.append(str(edge.get("target") or ""))
    for mapping in (
        reasoning_state.related_files,
        reasoning_state.related_tests,
        reasoning_state.related_configs,
        reasoning_state.related_docs,
        reasoning_state.impacted_files,
        reasoning_state.dependency_map,
    ):
        for source, targets in mapping.items():
            nodes.append(source)
            nodes.extend(targets)
    seen: set[str] = set()
    clean: list[str] = []
    for path in nodes:
        value = str(path or "").replace("\\", "/").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        clean.append(value)
    return clean[:200]
