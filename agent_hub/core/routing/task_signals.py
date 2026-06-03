from __future__ import annotations

from ...config import AgentConfig, is_free_agent
from ...models import HubRequest
from ...payloads import content_to_text, request_text


def _looks_like_coding_task(text: str) -> bool:
    return any(
        word in text
        for word in (
            "bug",
            "code",
            "debug",
            "edit",
            "error",
            "fix",
            "implement",
            "refactor",
            "repo",
            "test",
            "workspace",
        )
    )


def _classification_text(request: HubRequest) -> str:
    parts = [request.task or "", request.context or ""]
    for message in request.messages:
        if message.get("agent_hub_repo_context"):
            continue
        parts.append(content_to_text(message.get("content")))
    return "\n".join(part for part in parts if part)


def _looks_like_debug_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "debug",
            "failing",
            "failure",
            "traceback",
            "exception",
            "regression",
            "not working",
        )
    )


def _looks_like_review_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "review",
            "audit",
            "check my",
            "critique",
            "risk",
            "security",
            "correctness",
        )
    )


def _looks_like_research_task(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "research",
            "investigate",
            "find out",
            "compare",
            "summarize",
            "search",
            "evaluate",
        )
    )


def _looks_like_reasoning_task(text: str) -> bool:
    return any(
        word in text
        for word in (
            "analyze",
            "compare",
            "explain",
            "plan",
            "prove",
            "reason",
            "review",
            "tradeoff",
            "why",
        )
    )


def _repo_or_tool_task(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and hub_options.get("enable_builtin_tools") is False:
        return False
    if isinstance(hub_options, dict) and hub_options.get("enable_builtin_tools") is True:
        return True
    return _tool_task_requested(request)


def _tool_task_requested(request: HubRequest) -> bool:
    text = request_text(request).lower()
    return any(
        marker in text
        for marker in (
            "read ",
            "search",
            "file",
            "repo",
            "workspace",
            "run ",
            "command",
            "test",
            "edit",
            "write",
            "debug",
            "refactor",
        )
    )


def _repo_context_useful(request: HubRequest) -> bool:
    if _agent_runner_managed_request(request):
        return False
    route = str(request.route or "").lower()
    if route in {"coding", "local-agent", "agent-hub-coding", "debug", "review", "refactor"}:
        return True
    raw = request.raw if isinstance(request.raw, dict) else {}
    workflow = str(raw.get("workflow") or raw.get("workflow_stage") or "").lower()
    if workflow in {"code", "debug", "review", "refactor"}:
        return True
    return _looks_like_coding_task(request_text(request).lower())


def _agent_runner_managed_request(request: HubRequest) -> bool:
    raw = request.raw if isinstance(request.raw, dict) else {}
    return isinstance(raw.get("agent_hub_runtime"), dict)


def _recommendation_reason(
    agent: AgentConfig,
    *,
    text: str,
    prefer: str | None,
    index: int,
) -> str:
    reasons: list[str] = []
    lowered = text.lower()
    if _looks_like_coding_task(lowered) and agent.coding_score is not None:
        reasons.append(f"coding {agent.coding_score:g}")
    if (_looks_like_reasoning_task(lowered) or prefer == "reasoning") and agent.reasoning_score is not None:
        reasons.append(f"reasoning {agent.reasoning_score:g}")
    if prefer == "speed" and agent.speed_score is not None:
        reasons.append(f"speed {agent.speed_score:g}")
    if agent.context_window:
        reasons.append(f"{agent.context_window} token context")
    if agent.supports_tools or agent.supports_function_calling:
        reasons.append("tool support")
    if is_free_agent(agent):
        reasons.append("free/local eligible")
    if not reasons:
        reasons.append(f"route position {index + 1}")
    return ", ".join(reasons[:4])


__all__ = [
    "_agent_runner_managed_request",
    "_classification_text",
    "_looks_like_coding_task",
    "_looks_like_debug_task",
    "_looks_like_reasoning_task",
    "_looks_like_research_task",
    "_looks_like_review_task",
    "_recommendation_reason",
    "_repo_context_useful",
    "_repo_or_tool_task",
    "_tool_task_requested",
]
