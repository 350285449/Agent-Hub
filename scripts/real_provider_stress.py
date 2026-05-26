from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agent_hub.config import load_config
from agent_hub.core.router import AgentRouter, RouterError
from agent_hub.models import HubRequest


SCENARIOS = (
    "weak_free_provider_rate_limits",
    "provider_timeout",
    "malformed_streaming_chunks",
    "slow_streaming",
    "fallback_after_failure",
)


def main() -> int:
    if os.environ.get("AGENT_HUB_RUN_REAL_PROVIDER_STRESS") != "1":
        print("Real-provider stress harness is disabled. Set AGENT_HUB_RUN_REAL_PROVIDER_STRESS=1 to run.")
        print("Scenarios:", ", ".join(SCENARIOS))
        return 0

    config_path = Path(os.environ.get("AGENT_HUB_STRESS_CONFIG", "agent-hub.config.json"))
    route = os.environ.get("AGENT_HUB_STRESS_ROUTE", "cloud-agent")
    iterations = max(1, min(int(os.environ.get("AGENT_HUB_STRESS_ITERATIONS", "3")), 25))
    config = load_config(config_path)
    router = AgentRouter(config)
    rows = []
    for index in range(iterations):
        started = time.perf_counter()
        try:
            response = router.route(
                HubRequest(
                    session_id=f"stress-{index}",
                    route=route,
                    messages=[{"role": "user", "content": "Reply with exactly one short sentence."}],
                    record_session=False,
                )
            )
            rows.append(
                {
                    "iteration": index,
                    "ok": True,
                    "agent": response.agent,
                    "model": response.model,
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "failover": [event.to_dict() for event in response.failover],
                }
            )
        except RouterError as exc:
            rows.append(
                {
                    "iteration": index,
                    "ok": False,
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "error": str(exc),
                    "failover": [event.to_dict() for event in exc.failover],
                }
            )
    print(json.dumps({"route": route, "iterations": iterations, "results": rows}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
