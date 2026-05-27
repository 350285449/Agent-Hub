from __future__ import annotations

import json
import unittest

from scripts.stress_cline_failover import run_stress, validate_summary


class ClineFailoverStressTests(unittest.TestCase):
    def test_cline_failover_stress_uses_real_http_routing_surface(self) -> None:
        summary = run_stress(sequential_requests=20, concurrent_requests=5)
        failures = validate_summary(summary)

        self.assertEqual([], failures, json.dumps(_compact_summary(summary), indent=2))
        self.assertGreaterEqual(summary["sequential_requests"], 20)
        self.assertGreaterEqual(summary["concurrent_requests"], 5)
        self.assertGreaterEqual(summary["total_requests"], 26)

        results = summary["results"]
        self.assertTrue(any(result.get("failover") for result in results))
        self.assertFalse(any("stall-start stall-start" in result.get("text", "") for result in results))
        self.assertTrue(any("cutoff-part cutoff-finished" in result.get("text", "") for result in results))
        self.assertTrue(
            any("context preserved after overflow fallback" in result.get("text", "") for result in results)
        )

        health = summary["health"]["health"]
        self.assertEqual("cline", health["flaky"]["last_request_source"])
        self.assertGreater(health["flaky"]["failure_count"], 0)
        self.assertGreater(health["flaky"]["stream_interruption_count"], 0)
        self.assertGreater(health["steady"]["success_count"], 0)
        self.assertGreater(
            sum(row.get("tokens_in", 0) + row.get("tokens_out", 0) for row in health.values()),
            0,
        )

        routing_health = summary["routing"]["provider_health"]
        self.assertEqual(set(health), set(routing_health))
        for row in health.values():
            if row.get("quota_state") == "unknown":
                self.assertNotEqual(0, row.get("remaining"))


def _compact_summary(summary: dict) -> dict:
    health = summary.get("health", {}).get("health", {})
    return {
        "validation_failures": summary.get("validation_failures"),
        "provider_call_counts": summary.get("provider_call_counts"),
        "result_scenarios": [
            {
                "scenario": result.get("scenario"),
                "stream": result.get("stream"),
                "text": result.get("text"),
                "failover": result.get("failover"),
            }
            for result in summary.get("results", [])
        ],
        "health": {
            name: {
                "available": row.get("available"),
                "degraded": row.get("degraded"),
                "quota_state": row.get("quota_state"),
                "remaining": row.get("remaining"),
                "success_count": row.get("success_count"),
                "failure_count": row.get("failure_count"),
                "stream_interruption_count": row.get("stream_interruption_count"),
                "last_request_source": row.get("last_request_source"),
            }
            for name, row in health.items()
        },
    }
