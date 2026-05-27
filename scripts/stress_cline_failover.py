from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import ProviderError
from agent_hub.providers.base import StreamChunk
from agent_hub.server import AgentHubHTTPServer


SCENARIOS = (
    "long streaming request",
    "provider 429 failure",
    "quota exhaustion",
    "provider timeout",
    "stalled stream",
    "malformed streaming chunks",
    "context overflow",
    "output token cutoff",
    "provider cooldown",
    "slow provider",
    "provider recovery after cooldown",
)


@dataclass(slots=True)
class StressState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    calls: list[dict[str, Any]] = field(default_factory=list)
    by_agent: dict[str, int] = field(default_factory=dict)
    output_cutoff_calls: int = 0
    cooldown_failure_emitted: bool = False

    def record(self, agent: str, kind: str, request: HubRequest) -> None:
        with self.lock:
            self.by_agent[agent] = self.by_agent.get(agent, 0) + 1
            self.calls.append(
                {
                    "time": time.time(),
                    "agent": agent,
                    "kind": kind,
                    "source": request.metadata.get("source"),
                    "route": request.route,
                    "session_id": request.session_id,
                    "stream": request.stream,
                    "scenario": scenario_from_request(request),
                }
            )


class ClineStressProvider:
    def __init__(self, agent: AgentConfig, state: StressState) -> None:
        self.agent = agent
        self.state = state

    def supports_streaming(self) -> bool:
        return bool(self.agent.supports_streaming)

    def complete(self, request: HubRequest) -> ProviderResult:
        self.state.record(self.agent.name, "complete", request)
        scenario = scenario_from_request(request)

        if self.agent.name == "tiny":
            raise ProviderError(
                "tiny context probe should be preflight-skipped",
                retryable=True,
                error_type="context_too_large",
                cooldown_seconds=0.01,
            )
        if self.agent.name == "flaky":
            return self._flaky_complete(request, scenario)
        if self.agent.name == "slow" and scenario == "slow provider":
            time.sleep(0.025)
            return _result(self.agent, "slow response should be deprioritized")
        return self._healthy_complete(request, scenario)

    def stream(self, request: HubRequest):
        self.state.record(self.agent.name, "stream", request)
        scenario = scenario_from_request(request)
        if self.agent.name == "flaky":
            if scenario == "stalled stream":
                yield StreamChunk(text="stall-start ", delta={"content": "stall-start "}, model=self.agent.model)
                time.sleep(0.035)
                yield StreamChunk(text="stall-start duplicate", delta={"content": "stall-start duplicate"}, model=self.agent.model)
                return
            if scenario == "malformed streaming chunks":
                yield {"malformed": {"not": "a chat delta"}}
                yield StreamChunk(text="malformed-ok ", delta={"content": "malformed-ok "}, model=self.agent.model)
                return
            if scenario == "long streaming request":
                raise ProviderError("stream provider unavailable", error_type="provider_unavailable", cooldown_seconds=0.05)
        yield from self._healthy_stream(request, scenario)

    def _flaky_complete(self, request: HubRequest, scenario: str) -> ProviderResult:
        if scenario == "provider 429 failure":
            raise ProviderError(
                "rate limit exceeded",
                status_code=429,
                retryable=True,
                error_type="temporary_rate_limit",
                cooldown_seconds=0.05,
            )
        if scenario == "quota exhaustion":
            raise ProviderError(
                "quota exhausted",
                status_code=429,
                retryable=True,
                error_type="quota_exhausted",
                cooldown_seconds=0.05,
            )
        if scenario == "provider timeout":
            raise ProviderError(
                "provider request timed out",
                retryable=True,
                error_type="provider_unavailable",
                cooldown_seconds=0.05,
            )
        if scenario == "provider cooldown":
            with self.state.lock:
                if self.state.cooldown_failure_emitted:
                    return _result(self.agent, "flaky available after cooldown probe")
                self.state.cooldown_failure_emitted = True
            raise ProviderError(
                "cooldown probe failure",
                retryable=True,
                error_type="provider_overloaded",
                cooldown_seconds=0.5,
            )
        if scenario == "slow provider":
            raise ProviderError(
                "force slow provider check",
                retryable=True,
                error_type="provider_unavailable",
                cooldown_seconds=0.01,
            )
        if scenario == "output token cutoff":
            with self.state.lock:
                self.state.output_cutoff_calls += 1
                call_count = self.state.output_cutoff_calls
            if call_count % 2 == 1:
                return _result(self.agent, "cutoff-part ", finish_reason="length")
            raise ProviderError(
                "same provider continuation unavailable",
                retryable=True,
                error_type="provider_unavailable",
                cooldown_seconds=0.05,
            )
        if scenario == "context overflow":
            return _result(self.agent, "context preserved after overflow fallback")
        if scenario == "provider recovery after cooldown":
            return _result(
                self.agent,
                "flaky recovered after cooldown",
                quota={"requests_remaining": 9, "tokens_remaining": 9000},
            )
        return _result(self.agent, "flaky normal")

    def _healthy_complete(self, request: HubRequest, scenario: str) -> ProviderResult:
        prefix = _spaced_prefix(_partial_prefix(request))
        if scenario == "output token cutoff":
            return _result(self.agent, f"{prefix}cutoff-finished")
        if scenario == "context overflow":
            return _result(self.agent, "context preserved after overflow fallback")
        return _result(self.agent, f"{prefix}{self.agent.name} handled {scenario}")

    def _healthy_stream(self, request: HubRequest, scenario: str):
        prefix = _spaced_prefix(_partial_prefix(request))
        text = f"{prefix}{self.agent.name} streamed {scenario} done"
        for chunk in _chunk_text(text, size=32):
            yield StreamChunk(text=chunk, delta={"content": chunk}, model=self.agent.model)
            time.sleep(0.001)
        yield StreamChunk(text="", delta={}, model=self.agent.model, finish_reason="stop")


def run_stress(
    *,
    sequential_requests: int = 30,
    concurrent_requests: int = 8,
    include_streaming: bool = True,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = StressState()
        config = stress_config(root)
        server = AgentHubHTTPServer(("127.0.0.1", 0), config)
        server.router.provider_factory = lambda agent: ClineStressProvider(agent, state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            sequential: list[dict[str, Any]] = []
            previous_scenario = ""
            for index in range(sequential_requests):
                scenario = SCENARIOS[index % len(SCENARIOS)]
                if previous_scenario != "provider cooldown":
                    time.sleep(0.06)
                sequential.append(
                    _send_request(
                        base,
                        index,
                        stream=include_streaming and _stream_index(index),
                        scenario=scenario,
                    )
                )
                previous_scenario = scenario
            time.sleep(0.18)
            recovery_probe = _send_request(
                base,
                sequential_requests + 10_000,
                scenario="provider recovery after cooldown",
                stream=False,
            )
            with ThreadPoolExecutor(max_workers=max(1, concurrent_requests)) as executor:
                futures = [
                    executor.submit(
                        _send_request,
                        base,
                        sequential_requests + index,
                        include_streaming and _stream_index(index),
                    )
                    for index in range(concurrent_requests)
                ]
                concurrent = [future.result() for future in as_completed(futures)]
            health = _get_json(f"{base}/v1/provider-health")
            routing = _get_json(f"{base}/v1/routing/status")
            limits = _get_json(f"{base}/v1/limits")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    results = [*sequential, recovery_probe, *concurrent]
    summary = {
        "sequential_requests": sequential_requests,
        "concurrent_requests": concurrent_requests,
        "total_requests": len(results),
        "results": results,
        "provider_calls": list(state.calls),
        "provider_call_counts": dict(state.by_agent),
        "health": health,
        "routing": routing,
        "limits": limits,
    }
    summary["validation_failures"] = validate_summary(summary)
    return summary


def validate_summary(summary: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    if not results:
        return ["no requests executed"]
    if not any(result.get("failover") for result in results if isinstance(result, dict)):
        failures.append("failover did not occur")
    if any("stall-start stall-start" in str(result.get("text") or "") for result in results if isinstance(result, dict)):
        failures.append("duplicated streamed output detected")
    if not any("cutoff-part cutoff-finished" in str(result.get("text") or "") for result in results if isinstance(result, dict)):
        failures.append("output continuation was not preserved")
    if not any("context preserved after overflow fallback" in str(result.get("text") or "") for result in results if isinstance(result, dict)):
        failures.append("context overflow fallback did not preserve continuity")
    health = summary.get("health", {}).get("health", {}) if isinstance(summary.get("health"), dict) else {}
    flaky = health.get("flaky", {}) if isinstance(health, dict) else {}
    slow = health.get("slow", {}) if isinstance(health, dict) else {}
    steady = health.get("steady", {}) if isinstance(health, dict) else {}
    if not flaky.get("failure_count"):
        failures.append("flaky provider failure was not tracked")
    if flaky.get("remaining") == 0 and flaky.get("quota_state") == "unknown":
        failures.append("unknown quota displayed as zero")
    if not steady.get("success_count"):
        failures.append("healthy fallback provider did not record success")
    if not any((row.get("last_request_source") == "cline") for row in health.values() if isinstance(row, dict)):
        failures.append("cline source was not synchronized into health")
    if not any((row.get("stream_interruption_count") or 0) > 0 for row in health.values() if isinstance(row, dict)):
        failures.append("stream interruptions were not tracked")
    if slow and not (slow.get("degraded") or slow.get("cooldown_until")):
        failures.append("slow provider was not degraded or cooled down")
    calls = summary.get("provider_calls") if isinstance(summary.get("provider_calls"), list) else []
    if not _cooldown_skip_observed(summary):
        failures.append("cooldown provider was not skipped after failure")
    if not summary.get("routing", {}).get("provider_health"):
        failures.append("routing status is disconnected from provider health")
    return failures


def stress_config(root: Path) -> HubConfig:
    agents = {
        "flaky": AgentConfig(
            name="flaky",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model="flaky-model",
            base_url="http://127.0.0.1:9999",
            free=True,
            supports_streaming=True,
            supports_json=True,
            context_window=32_000,
            cooldown_seconds=0.05,
            priority=180,
        ),
        "tiny": AgentConfig(
            name="tiny",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model="tiny-model",
            base_url="http://127.0.0.1:9999",
            free=True,
            supports_streaming=True,
            context_window=320,
            cooldown_seconds=0.01,
            priority=80,
        ),
        "slow": AgentConfig(
            name="slow",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model="slow-model",
            base_url="http://127.0.0.1:9999",
            free=True,
            supports_streaming=True,
            context_window=32_000,
            cooldown_seconds=0.05,
            speed_score=0.1,
            priority=60,
        ),
        "steady": AgentConfig(
            name="steady",
            provider="openai-compatible",
            provider_type="openai-compatible",
            model="steady-model",
            base_url="http://127.0.0.1:9999",
            free=True,
            supports_streaming=True,
            supports_tools=True,
            supports_json=True,
            context_window=64_000,
            cooldown_seconds=0.01,
            speed_score=0.9,
            priority=50,
        ),
    }
    route = ["flaky", "slow", "steady"]
    return HubConfig(
        state_dir=root / "state",
        workspace_dir=root,
        approval_mode="auto",
        free_only=False,
        enable_load_balancing=True,
        expose_routing_details=True,
        cline_compatibility_mode=False,
        force_compatibility_streaming=False,
        native_stream_failure_policy="recover",
        max_context_tokens=None,
        compatibility_mode={
            "minimal_tool_schema": True,
            "reduced_repo_context": True,
            "max_context_tokens": None,
        },
        routing={
            "unlimited_default": True,
            "max_tokens_mode": "auto",
            "context_budget_mode": "auto",
            "auto_failover": True,
            "auto_retry": True,
            "free_first": True,
            "prefer_available_quota": True,
            "failover_on_slow_stream": True,
            "failover_on_quota_exhaustion": True,
            "continue_after_output_limit": True,
            "max_provider_attempts": 5,
            "slow_first_token_timeout_seconds": 0.008,
            "stream_stall_timeout_seconds": 0.015,
            "min_tokens_per_second": 0,
            "cooldown_rate_limit_seconds": 0.05,
            "cooldown_overload_seconds": 0.05,
            "cooldown_quota_seconds": 0.05,
        },
        default_route=route,
        routes=[
            RouteRule(name="coding", agents=route),
            RouteRule(name="cloud-agent", agents=route),
            RouteRule(name="local-agent", agents=route),
        ],
        agents=agents,
    )


def scenario_from_request(request: HubRequest) -> str:
    text = " ".join(str(message.get("content") or "") for message in request.messages)
    for scenario in SCENARIOS:
        if scenario in text:
            return scenario
    return "normal request"


def _send_request(
    base: str,
    index: int,
    stream: bool = False,
    *,
    scenario: str | None = None,
) -> dict[str, Any]:
    scenario = scenario or SCENARIOS[index % len(SCENARIOS)]
    model = "agent:tiny" if scenario == "context overflow" else "agent-hub-coding"
    content = _scenario_prompt(index, scenario)
    payload = {
        "model": model,
        "stream": bool(stream),
        "messages": [{"role": "user", "content": content}],
        "metadata": {"session_id": f"cline-stress-{index}"},
    }
    started = time.perf_counter()
    if stream:
        text, failover = _post_stream(f"{base}/v1/chat/completions", payload)
    else:
        data = _post_json(f"{base}/v1/chat/completions", payload)
        text = data["choices"][0]["message"].get("content") or ""
        failover = data.get("failover") or data.get("agent_hub", {}).get("failover") or []
    return {
        "index": index,
        "scenario": scenario,
        "stream": stream,
        "text": text,
        "failover": failover,
        "latency_seconds": round(time.perf_counter() - started, 4),
    }


def _scenario_prompt(index: int, scenario: str) -> str:
    if scenario == "context overflow":
        return f"{scenario} request {index}\n" + ("context-token " * 2000)
    if scenario == "long streaming request":
        return f"{scenario} request {index}: stream many chunks and keep continuity."
    return f"{scenario} request {index}: preserve conversation continuity."


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Cline/Stress"},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_stream(url: str, payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Cline/Stress"},
    )
    text_parts: list[str] = []
    failover: list[dict[str, Any]] = []
    with urlopen(request, timeout=10) as response:
        raw = response.read().decode("utf-8")
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[len("data:") :].strip()
            for line in block.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    text_parts.append(delta["content"])
            hub = parsed.get("agent_hub") if isinstance(parsed.get("agent_hub"), dict) else {}
            if isinstance(hub.get("failover"), list):
                failover.extend(item for item in hub["failover"] if isinstance(item, dict))
    return "".join(text_parts), failover


def _partial_prefix(request: HubRequest) -> str:
    for message in reversed(request.messages):
        if message.get("agent_hub_partial_response"):
            return str(message.get("content") or "")
    return ""


def _spaced_prefix(prefix: str) -> str:
    if prefix and not prefix.endswith((" ", "\n", "\t")):
        return f"{prefix} "
    return prefix


def _result_has_failover_reason(result: dict[str, Any], needle: str) -> bool:
    for event in result.get("failover") or []:
        if isinstance(event, dict) and needle.lower() in str(event.get("reason") or "").lower():
            return True
    return False


def _cooldown_skip_observed(summary: dict[str, Any]) -> bool:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    if any(
        _result_has_failover_reason(result, "temporary cooldown")
        for result in results
        if isinstance(result, dict)
    ):
        return True
    calls = summary.get("provider_calls") if isinstance(summary.get("provider_calls"), list) else []
    for result in results:
        if not isinstance(result, dict) or result.get("scenario") != "provider cooldown":
            continue
        try:
            next_session = f"cline-stress-{int(result.get('index')) + 1}"
        except (TypeError, ValueError):
            continue
        next_calls = [
            call for call in calls
            if isinstance(call, dict) and call.get("session_id") == next_session
        ]
        if next_calls and not any(call.get("agent") == "flaky" for call in next_calls):
            return True
    return False


def _result(
    agent: AgentConfig,
    text: str,
    *,
    finish_reason: str = "stop",
    quota: dict[str, Any] | None = None,
) -> ProviderResult:
    raw: dict[str, Any] = {}
    if quota:
        raw["agent_hub_provider"] = {"quota": quota}
    return ProviderResult(
        text=text,
        model=agent.model,
        raw=raw,
        usage={"prompt_tokens": 12, "completion_tokens": max(1, len(text) // 4)},
        finish_reason=finish_reason,
    )


def _chunk_text(text: str, *, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _stream_index(index: int) -> bool:
    return SCENARIOS[index % len(SCENARIOS)] in {
        "long streaming request",
        "stalled stream",
        "malformed streaming chunks",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Cline failover stress tests.")
    parser.add_argument("--sequential", type=int, default=30)
    parser.add_argument("--concurrent", type=int, default=8)
    parser.add_argument("--no-streaming", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = run_stress(
        sequential_requests=max(20, min(args.sequential, 50)),
        concurrent_requests=max(5, min(args.concurrent, 10)),
        include_streaming=not args.no_streaming,
    )
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(
            "Cline stress: "
            f"{summary['total_requests']} requests, "
            f"{len(summary['validation_failures'])} validation failures"
        )
        if summary["validation_failures"]:
            for failure in summary["validation_failures"]:
                print(f"- {failure}")
    return 1 if summary["validation_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
