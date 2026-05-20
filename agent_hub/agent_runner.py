from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from typing import Any

from .agent_tools import AgentToolbox, tool_result_message
from .config import HubConfig
from .models import FailoverEvent, HubRequest, HubResponse
from .router import AgentRouter


class AgentRunner:
    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)

    def run(self, request: HubRequest) -> HubResponse:
        toolbox = AgentToolbox(self.config, request)
        messages = self._initial_messages(request, toolbox)
        max_steps = _request_int(request, "agent_max_steps", self.config.agent_max_steps)
        trace: list[dict[str, Any]] = []
        failover: list[FailoverEvent] = []
        last_response: HubResponse | None = None

        for step_number in range(1, max_steps + 1):
            step_request = replace(
                request,
                messages=messages,
                stream=False,
                use_session_history=False,
                record_session=False,
            )
            response = self.router.route(step_request)
            last_response = response
            failover.extend(response.failover)

            command = _command_from_response(response)
            if command["action"] == "tool":
                tool_name = str(command["tool"])
                args = command.get("args") if isinstance(command.get("args"), dict) else {}
                result = toolbox.run(tool_name, args)
                trace.append(
                    {
                        "step": step_number,
                        "agent": response.agent,
                        "provider": response.provider,
                        "model": response.model,
                        "tool": tool_name,
                        "args": args,
                        "result": result,
                    }
                )
                messages.append({"role": "assistant", "content": response.text})
                messages.append(tool_result_message(tool_name, result))
                continue

            if command["action"] == "final":
                final = self._with_agent_metadata(
                    response,
                    request=request,
                    text=str(command["answer"]),
                    trace=trace,
                    failover=failover,
                    stopped=False,
                )
                self._record_final(request, final)
                return final

            final = self._with_agent_metadata(
                response,
                request=request,
                text=response.text,
                trace=trace,
                failover=failover,
                stopped=False,
            )
            self._record_final(request, final)
            return final

        text = "Agent stopped before producing a final answer."
        if last_response and last_response.text:
            text = f"{text}\n\nLast model message:\n{last_response.text}"
        final = self._with_agent_metadata(
            last_response,
            request=request,
            text=text,
            trace=trace,
            failover=failover,
            stopped=True,
        )
        self._record_final(request, final)
        return final

    def _initial_messages(self, request: HubRequest, toolbox: AgentToolbox) -> list[dict[str, Any]]:
        request_with_history = self._with_session_history(request)
        return [
            {"role": "system", "content": toolbox.instructions()},
            *request_with_history.messages,
        ]

    def _with_session_history(self, request: HubRequest) -> HubRequest:
        if not request.use_session_history:
            return request
        history = self.router.session_store.load(request.session_id).get("messages", [])
        if not history:
            return request
        if _is_prefix(history, request.messages):
            return request
        if _is_prefix(request.messages, history):
            return replace(request, messages=list(history))
        return replace(request, messages=[*history, *request.messages])

    def _with_agent_metadata(
        self,
        response: HubResponse | None,
        *,
        request: HubRequest,
        text: str,
        trace: list[dict[str, Any]],
        failover: list[FailoverEvent],
        stopped: bool,
    ) -> HubResponse:
        raw = dict(response.raw) if response else {}
        existing_metadata = raw.get("agent_hub")
        base_metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
        raw["agent_hub"] = {
            **base_metadata,
            "mode": "agent",
            "steps": trace,
            "stopped": stopped,
        }
        if response:
            return HubResponse(
                request_id=response.request_id,
                session_id=request.session_id,
                agent=response.agent,
                provider=response.provider,
                model=response.model,
                public_model=response.public_model,
                text=text,
                usage=response.usage,
                raw=raw,
                finish_reason=response.finish_reason,
                failover=failover,
                citations=response.citations,
                search_results=response.search_results,
                images=response.images,
                related_questions=response.related_questions,
            )
        return HubResponse(
            request_id=f"hub-{uuid.uuid4().hex}",
            session_id=request.session_id,
            agent="agent-runner",
            provider="agent-hub",
            model="agent-runner",
            public_model=request.route or "agent-hub-local",
            text=text,
            raw=raw,
            failover=failover,
        )

    def _record_final(self, request: HubRequest, response: HubResponse) -> None:
        if request.record_session:
            self.router.session_store.record_turn(request, response)


def _command_from_response(response: HubResponse) -> dict[str, Any]:
    tool_call = _openai_tool_call(response.raw) or _anthropic_tool_call(response.raw)
    if tool_call:
        return tool_call

    data = _json_from_text(response.text)
    if not isinstance(data, dict):
        return {"action": "text"}

    action = str(data.get("action", "")).lower()
    if action == "tool" or "tool" in data:
        tool = data.get("tool") or data.get("name")
        if tool:
            args = data.get("args", data.get("arguments", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"input": args}
            return {"action": "tool", "tool": tool, "args": args if isinstance(args, dict) else {}}

    if action == "final" or "final" in data or "answer" in data:
        return {"action": "final", "answer": data.get("answer", data.get("final", ""))}

    return {"action": "text"}


def _openai_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    function = tool_calls[0].get("function") if isinstance(tool_calls[0], dict) else None
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str):
        return None
    args = function.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"action": "tool", "tool": name, "args": args if isinstance(args, dict) else {}}


def _anthropic_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    content = raw.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        args = item.get("input", {})
        if isinstance(name, str):
            return {"action": "tool", "tool": name, "args": args if isinstance(args, dict) else {}}
    return None


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _request_int(request: HubRequest, key: str, default: int) -> int:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    value = hub_options.get(key) if isinstance(hub_options, dict) and key in hub_options else raw.get(key)
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, 50))


def _is_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )
